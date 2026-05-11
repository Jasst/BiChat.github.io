"""
routes/wallet.py — Баланс, переводы, стейкинг, майнинг + глобальная статистика
"""
import time
import logging

from flask import Blueprint, jsonify, request, session

from config import (
    COIN, COIN_NAME, TRANSFER_FEE, MIN_STAKE_AMOUNT, BLOCK_REWARD, CONFIG,
    STAKING_FEE_POOL_ADDRESS, ENABLE_MINING, ENABLE_STAKING, MESSAGE_FEE
)
from services.wallet import staking_manager

logger = logging.getLogger(__name__)
wallet_bp = Blueprint('wallet', __name__)

_blockchain = None

def init_wallet_routes(blockchain) -> None:
    global _blockchain
    _blockchain = blockchain


@wallet_bp.route('/wallet/config')
def wallet_config():
    """Возвращает клиенту текущие настройки (майнинг, стейкинг, комиссии)."""
    return jsonify({
        'enable_mining': ENABLE_MINING,
        'enable_staking': ENABLE_STAKING,
        'message_fee': MESSAGE_FEE,
        'transfer_fee': TRANSFER_FEE,
        'block_reward': BLOCK_REWARD if ENABLE_MINING else 0,
        'coin_name': COIN_NAME,
        'coin_divisor': COIN,
    })


@wallet_bp.route('/wallet/balance')
def wallet_balance():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    addr = session['address']
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('SELECT balance FROM wallets WHERE address = ?', (addr,))
        row = cursor.fetchone()
        balance = row[0] if row else 0
        cursor.execute('SELECT SUM(amount) FROM stakes WHERE address=? AND active=1', (addr,))
        stake_row = cursor.fetchone()
        staked = stake_row[0] if stake_row and stake_row[0] else 0
    return jsonify({
        'address': addr,
        'balance': balance,
        'staked': staked,
        'coin': COIN,
        'coin_name': COIN_NAME
    })


@wallet_bp.route('/wallet/transactions')
def wallet_transactions():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    addr = session['address']
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('''
            SELECT id, tx_type, sender, recipient, amount, timestamp
            FROM coin_transactions
            WHERE sender = ? OR recipient = ?
            ORDER BY timestamp DESC LIMIT 50
        ''', (addr, addr))
        txs = [{'id': r[0], 'type': r[1], 'sender': r[2],
                'recipient': r[3], 'amount': r[4], 'timestamp': r[5]}
               for r in cursor.fetchall()]
    return jsonify({'transactions': txs})


@wallet_bp.route('/wallet/send', methods=['POST'])
def wallet_send():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user = session['address']
    data = request.get_json()
    recipient = data.get('recipient', '').strip().lower()
    try:
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400

    if amount <= 0:
        return jsonify({'error': 'Amount must be positive'}), 400
    if len(recipient) != 64 or not all(c in '0123456789abcdef' for c in recipient):
        return jsonify({'error': 'Invalid recipient address'}), 400
    if recipient == user:
        return jsonify({'error': 'Cannot send to yourself'}), 400

    total = amount + TRANSFER_FEE
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute('SELECT balance FROM wallets WHERE address = ?', (user,))
        row     = cursor.fetchone()
        balance = row[0] if row else 0
        if balance < total:
            cursor.execute("ROLLBACK")
            return jsonify({'error': f'Insufficient balance. Need {total / COIN} {COIN_NAME}'}), 400

        cursor.execute('UPDATE wallets SET balance = balance - ? WHERE address = ?', (total, user))
        cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                       (recipient, amount, amount))
        ts = time.time()
        cursor.execute('INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp) VALUES (?,?,?,?,?)',
                       ('transfer', user, recipient, amount, ts))
        # Комиссия в стейкинг-пул
        cursor.execute('INSERT INTO wallets (address, balance) VALUES (?, ?) ON CONFLICT(address) DO UPDATE SET balance = balance + ?',
                       (STAKING_FEE_POOL_ADDRESS, TRANSFER_FEE, TRANSFER_FEE))
        cursor.execute('INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note) VALUES (?,?,?,?,?,?)',
                       ('fee', user, STAKING_FEE_POOL_ADDRESS, TRANSFER_FEE, ts, 'transfer fee to staking pool'))

        # Обновляем аккумулятор стейкинга (в той же транзакции)
        if ENABLE_STAKING and staking_manager:
            staking_manager.add_to_fee_pool(TRANSFER_FEE, cursor=cursor)

        cursor.execute("COMMIT")
    return jsonify({'message': 'Sent', 'amount': amount, 'fee': TRANSFER_FEE, 'coin_name': COIN_NAME}), 200

@wallet_bp.route('/wallet/stake', methods=['POST'])
def stake():
    if not ENABLE_STAKING:
        return jsonify({'error': 'Staking is disabled'}), 403
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    try:
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400
    if amount < MIN_STAKE_AMOUNT:
        return jsonify({'error': f'Minimum stake is {MIN_STAKE_AMOUNT / COIN:.6f} {COIN_NAME}'}), 400
    unlock_block = staking_manager.stake(session['address'], amount)
    if unlock_block == -1:
        return jsonify({'error': 'Insufficient balance'}), 400
    return jsonify({'message': 'Staked', 'unlock_block': unlock_block}), 200


@wallet_bp.route('/wallet/unstake', methods=['POST'])
def unstake():
    if not ENABLE_STAKING:
        return jsonify({'error': 'Staking is disabled'}), 403
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if staking_manager.unstake(session['address']):
        return jsonify({'message': 'Unstaked'}), 200
    return jsonify({'error': 'No active stake or still locked'}), 400


@wallet_bp.route('/wallet/staking/info')
def staking_info():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    addr = session['address']
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        cursor.execute('SELECT amount, start_time, start_block, unlock_block FROM stakes WHERE address=? AND active=1',
                       (addr,))
        stakes = [dict(row) for row in cursor.fetchall()]
        # Получаем current_block здесь, пока курсор ещё открыт
        current_block = _blockchain._last_block_raw(cursor).get('index', 0)

    expected_income = 0
    if ENABLE_STAKING and staking_manager:
        expected_income = staking_manager.get_expected_income(addr)

    return jsonify({
        'stakes': stakes,
        'expected_income': expected_income,
        'current_block': current_block,
        'coin_name': COIN_NAME,
        'coin_divisor': COIN
    })



@wallet_bp.route('/wallet/last-proof')
def last_proof():
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        last = _blockchain._last_block_raw(cursor)
    return jsonify({'last_proof': last.get('proof', 0), 'difficulty': CONFIG['POW_DIFFICULTY']})


@wallet_bp.route('/wallet/mine', methods=['POST'])
def mine():
    if not ENABLE_MINING:
        return jsonify({'error': 'Mining is disabled'}), 403
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json()
    proof = data.get('proof')
    if proof is None:
        return jsonify({'error': 'proof required'}), 400
    from database import get_db_cursor
    with get_db_cursor(_blockchain.db_path) as cursor:
        last = _blockchain._last_block_raw(cursor)
        if not last:
            return jsonify({'error': 'No blockchain'}), 500
        if not _blockchain.valid_proof(last['proof'], proof):
            return jsonify({'error': 'Invalid proof'}), 400
        _blockchain._new_block_raw(cursor, proof, miner_address=session['address'])
    return jsonify({'message': 'Block mined', 'reward': BLOCK_REWARD}), 200


@wallet_bp.route('/wallet/global-stats')
def wallet_global_stats():
    """Возвращает глобальную статистику сети."""
    from database import get_db_cursor
    from config import BLOCK_REWARD, COIN, CONFIG, MAX_SUPPLY

    with get_db_cursor(_blockchain.db_path) as cursor:
        # Общая эмиссия
        cursor.execute('SELECT SUM(balance) FROM wallets')
        total_supply_raw = cursor.fetchone()[0] or 0

        # Баланс стейкинг-пула
        cursor.execute('SELECT balance FROM wallets WHERE address = ?', (STAKING_FEE_POOL_ADDRESS,))
        row = cursor.fetchone()
        staking_pool_balance = row[0] if row else 0

        # Количество блоков
        cursor.execute('SELECT COUNT(*) FROM blockchain')
        total_blocks = cursor.fetchone()[0] or 0

        # Сумма активных стейков
        cursor.execute('SELECT SUM(amount) FROM stakes WHERE active = 1')
        total_staked_raw = cursor.fetchone()[0] or 0

    # Оставшиеся монеты
    if MAX_SUPPLY is not None:
        remaining = max(0, MAX_SUPPLY - total_supply_raw)
    else:
        remaining = None

    return jsonify({
        'total_supply': total_supply_raw,
        'staking_pool_balance': staking_pool_balance,
        'block_reward': BLOCK_REWARD if ENABLE_MINING else 0,
        'total_blocks': total_blocks,
        'total_staked': total_staked_raw,
        'difficulty': CONFIG['POW_DIFFICULTY'],
        'coin_name': COIN_NAME,
        'coin_divisor': COIN,
        'max_supply': MAX_SUPPLY,
        'remaining_supply': remaining,
        'message_fee': MESSAGE_FEE,
    })