"""routes/wallet_async.py — Кошелёк, переводы, стейкинг, майнинг (асинхронная версия)"""
import json
import logging
import secrets
import hashlib
import time
from datetime import datetime
from typing import Optional

from quart import Blueprint, jsonify, request

from database_async import db
from redis_manager import redis_manager
from config_async import (
    COIN, COIN_NAME, TRANSFER_FEE, MIN_STAKE_AMOUNT, BLOCK_REWARD,
    STAKING_FEE_POOL_ADDRESS, ENABLE_MINING, ENABLE_STAKING, MESSAGE_FEE,
    POW_DIFFICULTY, POW_MAX_ITERATIONS, MAX_SUPPLY
)

logger = logging.getLogger(__name__)
wallet_bp = Blueprint('wallet', __name__)

MINING_CHALLENGE_TTL = 60   # секунд
REWARD_PRECISION = 10**12   # для расчётов стейкинга


# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def valid_proof_with_challenge(last_proof: int, proof: int, challenge: str,
                                difficulty: int = None) -> bool:
    """Проверяет proof-of-work для майнинга."""
    if difficulty is None:
        difficulty = POW_DIFFICULTY
    guess = f"{last_proof}{challenge}{proof}".encode()
    return hashlib.sha256(guess).hexdigest().startswith('0' * difficulty)


async def _get_staking_acc_reward(cursor=None) -> int:
    """Получает текущее значение acc_reward_per_stake"""
    if cursor:
        val = await cursor.fetchval(
            "SELECT value FROM staking_state WHERE key = 'acc_reward_per_stake'"
        )
    else:
        val = await db.fetch_val(
            "SELECT value FROM staking_state WHERE key = 'acc_reward_per_stake'"
        )
    return int(val) if val else 0


async def _update_staking_acc_reward(amount_sats: int, cursor=None) -> None:
    """Обновляет acc_reward_per_stake при добавлении комиссий в пул"""
    if cursor:
        total_staked = await cursor.fetchval(
            "SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE active = TRUE"
        ) or 0
        current_acc = await _get_staking_acc_reward(cursor)
    else:
        total_staked = await db.fetch_val(
            "SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE active = TRUE"
        ) or 0
        current_acc = await _get_staking_acc_reward()

    if total_staked == 0:
        return

    new_acc = current_acc + (amount_sats * REWARD_PRECISION) // total_staked

    if cursor:
        await cursor.execute(
            "UPDATE staking_state SET value = $1 WHERE key = 'acc_reward_per_stake'",
            str(new_acc)
        )
    else:
        await db.execute(
            "UPDATE staking_state SET value = $1 WHERE key = 'acc_reward_per_stake'",
            str(new_acc)
        )


# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

@wallet_bp.route('/wallet/config', methods=['GET'])
async def wallet_config():
    """Возвращает клиенту текущие настройки"""
    return jsonify({
        'enable_mining': ENABLE_MINING,
        'enable_staking': ENABLE_STAKING,
        'message_fee': MESSAGE_FEE,
        'transfer_fee': TRANSFER_FEE,
        'block_reward': BLOCK_REWARD if ENABLE_MINING else 0,
        'coin_name': COIN_NAME,
        'coin_divisor': COIN,
        'pow_max_iterations': POW_MAX_ITERATIONS,
        'pow_difficulty': POW_DIFFICULTY,
    })


# =============================================================================
# БАЛАНС И ТРАНЗАКЦИИ
# =============================================================================

@wallet_bp.route('/wallet/balance', methods=['GET'])
async def wallet_balance():
    """Получить баланс кошелька"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    cache_key = f"balance:{address}"
    cached = await redis_manager.cache_get(cache_key)
    if cached:
        return jsonify(cached), 200

    balance = await db.fetch_val(
        "SELECT COALESCE(balance, 0) FROM wallets WHERE address = $1", address
    ) or 0

    staked = await db.fetch_val("""
        SELECT COALESCE(SUM(amount), 0) FROM stakes
        WHERE address = $1 AND active = TRUE
    """, address) or 0

    result = {
        'address': address,
        'balance': balance,
        'staked': staked,
        'coin': COIN,
        'coin_name': COIN_NAME,
    }

    await redis_manager.cache_set(cache_key, result, ttl=30)
    return jsonify(result), 200


@wallet_bp.route('/wallet/transactions', methods=['GET'])
async def wallet_transactions():
    """Получить историю транзакций (последние 50)"""
    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    rows = await db.fetch_all("""
        SELECT id, tx_type, sender, recipient, amount,
               EXTRACT(EPOCH FROM timestamp) as ts
        FROM coin_transactions
        WHERE sender = $1 OR recipient = $1
        ORDER BY timestamp DESC
        LIMIT 50
    """, address)

    return jsonify({
        'transactions': [
            {
                'id': row['id'],
                'type': row['tx_type'],
                'sender': row['sender'],
                'recipient': row['recipient'],
                'amount': row['amount'],
                'timestamp': row['ts'],
            }
            for row in rows
        ]
    }), 200


# =============================================================================
# ПЕРЕВОДЫ
# =============================================================================

@wallet_bp.route('/wallet/send', methods=['POST'])
async def wallet_send():
    """Отправить монеты другому пользователю"""
    session_id = request.cookies.get('session_id')
    sender = await redis_manager.session_get(session_id, 'address')

    if not sender:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    recipient = data.get('recipient', '').strip().lower()

    try:
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400

    if amount <= 0:
        return jsonify({'error': 'Amount must be positive'}), 400

    if len(recipient) != 64 or not all(c in '0123456789abcdef' for c in recipient):
        return jsonify({'error': 'Invalid recipient address'}), 400

    if recipient == sender:
        return jsonify({'error': 'Cannot send to yourself'}), 400

    total = amount + TRANSFER_FEE

    async with db.transaction() as conn:
        balance = await conn.fetchval(
            "SELECT balance FROM wallets WHERE address = $1 FOR UPDATE", sender
        ) or 0

        if balance < total:
            return jsonify({
                'error': f'Insufficient balance. Need {total / COIN:.6f} {COIN_NAME}'
            }), 400

        await conn.execute(
            "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
            total, sender
        )
        await conn.execute("""
            INSERT INTO wallets (address, balance) VALUES ($1, $2)
            ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
        """, recipient, amount)
        await conn.execute("""
            INSERT INTO wallets (address, balance) VALUES ($1, $2)
            ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
        """, STAKING_FEE_POOL_ADDRESS, TRANSFER_FEE)
        await conn.execute("""
            INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp)
            VALUES ('transfer', $1, $2, $3, NOW())
        """, sender, recipient, amount)
        await conn.execute("""
            INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note)
            VALUES ('fee', $1, $2, $3, NOW(), $4)
        """, sender, STAKING_FEE_POOL_ADDRESS, TRANSFER_FEE, 'transfer fee to staking pool')

        if ENABLE_STAKING:
            await _update_staking_acc_reward(TRANSFER_FEE, cursor=conn)

    await redis_manager.cache_delete(f"balance:{sender}")
    await redis_manager.cache_delete(f"balance:{recipient}")

    logger.info(
        f"💸 Transfer: {amount / COIN:.6f} {COIN_NAME} "
        f"from {sender[:10]}... to {recipient[:10]}..."
    )

    return jsonify({'message': 'Sent', 'amount': amount, 'fee': TRANSFER_FEE,
                    'coin_name': COIN_NAME}), 200


# =============================================================================
# СТЕЙКИНГ
# =============================================================================

@wallet_bp.route('/wallet/stake', methods=['POST'])
async def stake():
    """Заморозить монеты для получения пассивного дохода"""
    if not ENABLE_STAKING:
        return jsonify({'error': 'Staking is disabled'}), 403

    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    try:
        amount = int(data.get('amount', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid amount'}), 400

    if amount < MIN_STAKE_AMOUNT:
        return jsonify({
            'error': f'Minimum stake is {MIN_STAKE_AMOUNT / COIN:.6f} {COIN_NAME}'
        }), 400

    async with db.transaction() as conn:
        balance = await conn.fetchval(
            "SELECT balance FROM wallets WHERE address = $1 FOR UPDATE", address
        ) or 0

        if balance < amount:
            return jsonify({'error': 'Insufficient balance'}), 400

        stake_count = await conn.fetchval(
            "SELECT COUNT(*) FROM stakes WHERE address = $1 AND active = TRUE", address
        ) or 0

        if stake_count >= 10:
            return jsonify({'error': 'Maximum 10 active stakes per user'}), 400

        last_block = await conn.fetchval(
            "SELECT block_index FROM blockchain ORDER BY block_index DESC LIMIT 1"
        ) or 0

        unlock_block = last_block + 100
        current_acc = await _get_staking_acc_reward(conn)

        await conn.execute(
            "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
            amount, address
        )
        await conn.execute("""
            INSERT INTO wallets (address, balance) VALUES ($1, $2)
            ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
        """, STAKING_FEE_POOL_ADDRESS, amount)
        await conn.execute("""
            INSERT INTO stakes (address, amount, start_time, start_block, unlock_block, active, reward_debt)
            VALUES ($1, $2, NOW(), $3, $4, TRUE, $5)
        """, address, amount, last_block, unlock_block, current_acc)
        await conn.execute("""
            INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note)
            VALUES ('stake', $1, $2, $3, NOW(), $4)
        """, address, STAKING_FEE_POOL_ADDRESS, amount, 'stake')

    await redis_manager.cache_delete(f"balance:{address}")

    logger.info(f"🔒 {address[:10]}... staked {amount / COIN:.6f} {COIN_NAME}")

    return jsonify({'message': 'Staked', 'unlock_block': unlock_block}), 200


@wallet_bp.route('/wallet/unstake', methods=['POST'])
async def unstake():
    """Разблокировать стейк и получить награду"""
    if not ENABLE_STAKING:
        return jsonify({'error': 'Staking is disabled'}), 403

    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    async with db.transaction() as conn:
        stakes = await conn.fetch("""
            SELECT id, amount, unlock_block, reward_debt FROM stakes
            WHERE address = $1 AND active = TRUE
        """, address)

        if not stakes:
            return jsonify({'error': 'No active stakes'}), 400

        current_block = await conn.fetchval(
            "SELECT block_index FROM blockchain ORDER BY block_index DESC LIMIT 1"
        ) or 0

        current_acc = await _get_staking_acc_reward(conn)
        any_unlocked = False

        for s in stakes:
            if current_block >= s['unlock_block']:
                any_unlocked = True

                reward = (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION
                total_payout = s['amount'] + reward

                pool_balance = await conn.fetchval(
                    "SELECT balance FROM wallets WHERE address = $1 FOR UPDATE",
                    STAKING_FEE_POOL_ADDRESS
                ) or 0

                if pool_balance < total_payout:
                    logger.error(f"Pool underfunded: need {total_payout}, have {pool_balance}")
                    continue

                await conn.execute(
                    "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
                    s['amount'], STAKING_FEE_POOL_ADDRESS
                )
                if reward > 0:
                    await conn.execute(
                        "UPDATE wallets SET balance = balance - $1 WHERE address = $2",
                        reward, STAKING_FEE_POOL_ADDRESS
                    )
                await conn.execute("""
                    INSERT INTO wallets (address, balance) VALUES ($1, $2)
                    ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
                """, address, total_payout)
                await conn.execute(
                    "UPDATE stakes SET active = FALSE WHERE id = $1", s['id']
                )
                await conn.execute("""
                    INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note)
                    VALUES ('unstake', $1, $2, $3, NOW(), $4)
                """, STAKING_FEE_POOL_ADDRESS, address, s['amount'], 'unstake principal')
                if reward > 0:
                    await conn.execute("""
                        INSERT INTO coin_transactions (tx_type, sender, recipient, amount, timestamp, note)
                        VALUES ('staking_reward', $1, $2, $3, NOW(), $4)
                    """, STAKING_FEE_POOL_ADDRESS, address, reward, 'staking income')

                logger.info(f"💰 {address[:10]}... earned {reward / COIN:.6f} from staking")

    if not any_unlocked:
        return jsonify({'error': 'No stakes are unlocked yet'}), 400

    await redis_manager.cache_delete(f"balance:{address}")
    logger.info(f"🔓 {address[:10]}... unstaked successfully")

    return jsonify({'message': 'Unstaked successfully'}), 200


@wallet_bp.route('/wallet/staking/info', methods=['GET'])
async def staking_info():
    """Информация о стейках пользователя"""
    if not ENABLE_STAKING:
        return jsonify({'error': 'Staking is disabled'}), 403

    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    # FIX: добавлен reward_debt в SELECT; расчёт по реальной формуле вместо * 0.001
    stakes = await db.fetch_all("""
        SELECT amount,
               EXTRACT(EPOCH FROM start_time) as start_time,
               start_block,
               unlock_block,
               reward_debt
        FROM stakes
        WHERE address = $1 AND active = TRUE
    """, address)

    current_block = await db.fetch_val(
        "SELECT block_index FROM blockchain ORDER BY block_index DESC LIMIT 1"
    ) or 0

    expected_income = 0
    if stakes:
        current_acc = await _get_staking_acc_reward()
        for s in stakes:
            expected_income += (s['amount'] * (current_acc - s['reward_debt'])) // REWARD_PRECISION

    return jsonify({
        'stakes': [dict(s) for s in stakes],
        'expected_income': expected_income,
        'current_block': current_block,
        'coin_name': COIN_NAME,
        'coin_divisor': COIN,
    }), 200


# =============================================================================
# МАЙНИНГ (PROOF-OF-WORK)
# =============================================================================

@wallet_bp.route('/wallet/last-proof', methods=['GET'])
async def last_proof():
    """Получить последний proof для майнинга (создаёт challenge)"""
    if not ENABLE_MINING:
        return jsonify({'error': 'Mining is disabled'}), 403

    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    last_block = await db.fetch_one("""
        SELECT block_index, proof FROM blockchain ORDER BY block_index DESC LIMIT 1
    """)

    if not last_block:
        return jsonify({'error': 'No blockchain found'}), 500

    challenge = secrets.token_hex(16)
    challenge_key = f"mining_challenge:{address}:{challenge}"
    await redis_manager.cache_set(challenge_key, {
        'last_proof': last_block['proof'],
        'last_index': last_block['block_index'],
        'created_at': time.time(),
    }, ttl=MINING_CHALLENGE_TTL)

    return jsonify({
        'last_proof': last_block['proof'],
        'last_index': last_block['block_index'],
        'difficulty': POW_DIFFICULTY,
        'challenge': challenge,
    }), 200


@wallet_bp.route('/wallet/mine', methods=['POST'])
async def mine():
    """Отправить найденный proof для создания нового блока"""
    if not ENABLE_MINING:
        return jsonify({'error': 'Mining is disabled'}), 403

    session_id = request.cookies.get('session_id')
    address = await redis_manager.session_get(session_id, 'address')

    if not address:
        return jsonify({'error': 'Unauthorized'}), 401

    data = await request.get_json()
    proof = data.get('proof')
    challenge = data.get('challenge')
    last_proof_val = data.get('last_proof')
    last_index = data.get('last_index')

    if not all([proof is not None, challenge, last_proof_val is not None, last_index is not None]):
        return jsonify({'error': 'Missing required fields: proof, challenge, last_proof, last_index'}), 400

    challenge_key = f"mining_challenge:{address}:{challenge}"
    challenge_data = await redis_manager.cache_get(challenge_key)

    if not challenge_data:
        return jsonify({'error': 'Invalid or expired challenge'}), 400

    if (challenge_data.get('last_proof') != last_proof_val or
            challenge_data.get('last_index') != last_index):
        return jsonify({'error': 'Challenge data mismatch'}), 400

    await redis_manager.cache_delete(challenge_key)

    current = await db.fetch_one("""
        SELECT block_index, proof FROM blockchain ORDER BY block_index DESC LIMIT 1
    """)

    if not current:
        return jsonify({'error': 'No blockchain'}), 500

    if current['proof'] != last_proof_val or current['block_index'] != last_index:
        return jsonify({'error': 'Blockchain moved, try again'}), 409

    if not valid_proof_with_challenge(last_proof_val, proof, challenge, POW_DIFFICULTY):
        return jsonify({'error': 'Invalid proof'}), 400

    async with db.transaction() as conn:
        current_again = await conn.fetchrow("""
            SELECT block_index, proof FROM blockchain ORDER BY block_index DESC LIMIT 1
            FOR UPDATE
        """)

        if (current_again['proof'] != last_proof_val or
                current_again['block_index'] != last_index):
            return jsonify({'error': 'Blockchain changed during validation'}), 409

        new_index = current_again['block_index'] + 1
        previous_hash = hashlib.sha256(
            f"{current_again['proof']}{current_again['block_index']}".encode()
        ).hexdigest()

        await conn.execute("""
            INSERT INTO blockchain (block_index, proof, previous_hash, timestamp)
            VALUES ($1, $2, $3, NOW())
        """, new_index, proof, previous_hash)

        await conn.execute("""
            INSERT INTO wallets (address, balance) VALUES ($1, $2)
            ON CONFLICT (address) DO UPDATE SET balance = wallets.balance + $2
        """, address, BLOCK_REWARD)

        await conn.execute("""
            INSERT INTO coin_transactions (tx_type, recipient, amount, timestamp, note)
            VALUES ('block_reward', $1, $2, NOW(), $3)
        """, address, BLOCK_REWARD, f'Miner reward for block {new_index}')

    await redis_manager.cache_delete(f"balance:{address}")

    logger.info(
        f"⛏️ Block {new_index} mined by {address[:10]}..., "
        f"reward: {BLOCK_REWARD / COIN:.6f} {COIN_NAME}"
    )

    return jsonify({
        'message': 'Block mined successfully',
        'reward': BLOCK_REWARD,
        'block_index': new_index,
        'coin_name': COIN_NAME,
    }), 200


# =============================================================================
# ГЛОБАЛЬНАЯ СТАТИСТИКА
# =============================================================================

@wallet_bp.route('/wallet/global-stats', methods=['GET'])
async def wallet_global_stats():
    """Возвращает глобальную статистику сети"""
    total_supply = await db.fetch_val(
        "SELECT COALESCE(SUM(balance), 0) FROM wallets"
    ) or 0

    pool_balance = await db.fetch_val(
        "SELECT balance FROM wallets WHERE address = $1", STAKING_FEE_POOL_ADDRESS
    ) or 0

    total_blocks = await db.fetch_val("SELECT COUNT(*) FROM blockchain") or 0

    total_staked = await db.fetch_val("""
        SELECT COALESCE(SUM(amount), 0) FROM stakes WHERE active = TRUE
    """) or 0

    remaining = None
    if MAX_SUPPLY is not None:
        remaining = max(0, MAX_SUPPLY - total_supply)

    return jsonify({
        'total_supply': total_supply,
        'staking_pool_balance': pool_balance,
        'block_reward': BLOCK_REWARD if ENABLE_MINING else 0,
        'total_blocks': total_blocks,
        'total_staked': total_staked,
        'difficulty': POW_DIFFICULTY,
        'coin_name': COIN_NAME,
        'coin_divisor': COIN,
        'max_supply': MAX_SUPPLY,
        'remaining_supply': remaining,
        'message_fee': MESSAGE_FEE,
        'transfer_fee': TRANSFER_FEE,
    }), 200