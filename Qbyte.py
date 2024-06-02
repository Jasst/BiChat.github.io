from qiskit import QuantumCircuit, Aer, execute

# Создаем квантовую схему с восьмью кубитами (для каждой буквы)
qc = QuantumCircuit(8)

# Устанавливаем начальные значения кубитов
initial_states = ['000', '111', '001', '100', '101', '010', '110', '011']

# Применяем гейт Адамара к каждому кубиту
for i, state in enumerate(initial_states):
    for j, bit in enumerate(state):
        if bit == '1':
            qc.x(j)  # Установка кубита в состояние '1'
    qc.h(range(8))  # Применяем гейт Адамара ко всем кубитам
    for j, bit in enumerate(state):
        if bit == '1':
            qc.x(j)  # Возвращаем кубит в исходное состояние

# Используем симулятор для выполнения схемы
simulator = Aer.get_backend('statevector_simulator')
result = execute(qc, simulator).result()

# Получаем вектор состояния
statevector = result.get_statevector()

# Подсчитываем количество состояний
num_states = len(statevector)

# Выводим количество состояний
print("Number of states:", num_states)
