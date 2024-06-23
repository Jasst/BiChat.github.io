import asyncio
import requests
from bs4 import BeautifulSoup
from transformers import pipeline

# Настройка предобученной модели трансформера
model_name = "distilbert-base-cased-distilled-squad"
nlp = pipeline("question-answering", model=model_name, tokenizer=model_name)

# Функция для анализа с использованием модели трансформера
async def analyze_with_transformer(prompt):
    context = "The context should be relevant to the question for the best results."  # Update with a relevant context
    result = nlp(question=prompt, context=context)
    return result

# Функция для выполнения поиска в Google и получения результата
async def search_with_google(prompt):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(f"https://www.google.com/search?q={prompt}", headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    result_stats = soup.find("div", id="result-stats")
    return result_stats.text if result_stats else "No result stats found"

# Основная асинхронная функция для выполнения задач
async def main(prompt):
    # Параллельное выполнение задач
    transformer_task = asyncio.create_task(analyze_with_transformer(prompt))
    google_task = asyncio.create_task(search_with_google(prompt))

    transformer_result = await transformer_task
    google_result = await google_task

    print(f"Transformer result: {transformer_result}")
    print(f"Google result: {google_result}")

# Запуск основной функции
prompt = input("Введите запрос: ")
asyncio.run(main(prompt))
