<?php
$db = new SQLite3(__DIR__ . '/blockchain.db');

$addr = 'e9a751094d1740e4c68233e16fbe8a92317cdd2e73154c5a39cd850f9e809828';

$result = $db->query("SELECT balance FROM wallets WHERE address = '$addr'");
$row = $result->fetchArray();
echo "Баланс кошелька: " . ($row ? $row['balance'] : '0') . " сатоши<br>";

$result = $db->query("SELECT * FROM coin_transactions WHERE recipient = '$addr' ORDER BY timestamp DESC LIMIT 10");
echo "Последние 10 транзакций на адрес:<br>";
while ($row = $result->fetchArray()) {
    echo "ID: {$row['id']}, тип: {$row['tx_type']}, сумма: {$row['amount']}, время: {$row['timestamp']}<br>";
}
?>