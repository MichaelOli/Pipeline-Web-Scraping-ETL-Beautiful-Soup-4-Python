import requests
from bs4 import BeautifulSoup
import time
import sqlite3
import pandas as pd
import asyncio
from telegram import Bot
import os
from dotenv import load_dotenv
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Carrega variáveis de ambiente
load_dotenv()

# Configurações do bot do Telegram
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
bot = Bot(token=TOKEN)

# Lista de URLs para monitoramento
PRODUCT_URLS = [
    'https://www.mercadolivre.com.br/carrinho-beb-conforto-moises-napoli-travel-system-galzerano-cor-preto/p/MLB24838651',
    'https://produto.mercadolivre.com.br/MLB-1231795719-berco-cama-multifuncional-com-cama-auxiliar-3-gavetas-de-_JM'  # Substitua pelo URL real de outro produto
]

def fetch_page(url):
    """Busca a página do produto e retorna o HTML."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.error(f"Erro ao buscar página {url}: {e}")
        return None

def parse_page(html):
    """Faz o parsing do HTML e extrai informações do produto."""
    if not html:
        logging.warning("HTML vazio recebido para parsing.")
        return None

    soup = BeautifulSoup(html, 'html.parser')
    try:
        # Extrair o nome do produto
        product_name = soup.find('h1', class_='ui-pdp-title').get_text(strip=True)
        
        # Extrair os preços
        prices = soup.find_all('span', class_='andes-money-amount__fraction')
        new_price = int(prices[0].get_text(strip=True).replace('.', '')) if len(prices) >= 1 else None
        installment_price = int(prices[1].get_text(strip=True).replace('.', '')) if len(prices) >= 2 else new_price
        
        # Preço original
        old_price_tag = soup.find('span', class_='andes-price__original-value')
        old_price = int(old_price_tag.get_text(strip=True).replace('.', '')) if old_price_tag else 0

        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')

        if not new_price:
            logging.warning("Preço atual não encontrado.")
            return None

        return {
            'product_name': product_name,
            'old_price': old_price,
            'new_price': new_price,
            'installment_price': installment_price,
            'timestamp': timestamp
        }
    except AttributeError as e:
        logging.error(f"Erro ao parsear HTML: {e}")
        return None

def create_connection(db_name='CarrinhoDoJoaodb'):
    """Cria uma conexão com o banco de dados SQLite."""
    return sqlite3.connect(db_name)

def setup_database(conn):
    """Cria a tabela de preços se ela não existir."""
    with conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT,
                old_price INTEGER,
                new_price INTEGER,
                installment_price INTEGER,
                timestamp TEXT
            )
        ''')

def save_to_database(conn, data):
    """Salva uma linha de dados no banco de dados SQLite."""
    if data:
        pd.DataFrame([data]).to_sql('prices', conn, if_exists='append', index=False)
    else:
        logging.warning("Nenhum dado a ser salvo.")

def get_max_price(conn, product_name):
    """Consulta o maior preço registrado para um produto específico."""
    query = "SELECT MAX(new_price), timestamp FROM prices WHERE product_name = ?"
    result = conn.execute(query, (product_name,)).fetchone()
    return result if result[0] is not None else (None, None)

async def send_telegram_message(product_name, current_price, installment_price, max_price, max_price_timestamp):
    """Envia uma mensagem para o Telegram."""
    try:
        message = (
            f"📊 *Monitoramento de Preços:*\n\n"
            f"Produto: *{product_name}*\n"
            f"Preço Atual: R$ {current_price}\n"
            f"Preço Parcelado/Promocional: R$ {installment_price}\n"
        )
        if max_price is None:
            message += "Este é o primeiro registro de preço.\n"
        elif current_price > max_price:
            message += f"Novo preço maior registrado!\n"
        else:
            message += f"Maior preço registrado: R$ {max_price} em {max_price_timestamp}\n"

        await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Erro ao enviar mensagem para o Telegram: {e}")

async def main():
    conn = create_connection()
    setup_database(conn)
    interval = 300  # Intervalo em segundos

    try:
        while True:
            for url in PRODUCT_URLS:
                page_content = fetch_page(url)
                product_info = parse_page(page_content)
                if not product_info:
                    continue

                current_price = product_info['new_price']
                installment_price = product_info['installment_price']
                product_name = product_info['product_name']
                max_price, max_price_timestamp = get_max_price(conn, product_name)

                await send_telegram_message(product_name, current_price, installment_price, max_price, max_price_timestamp)
                save_to_database(conn, product_info)

            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        logging.info("Execução interrompida.")
    finally:
        conn.close()

if __name__ == '__main__':
    asyncio.run(main())
