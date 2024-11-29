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

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,  # Exibe INFO ou acima no terminal
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Exibe no terminal
        logging.FileHandler('scraping_log.log', mode='a')  # Grava no arquivo
    ]
)

# Carrega variáveis de ambiente
load_dotenv()

# Configurações do bot do Telegram
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
bot = Bot(token=TOKEN)

# Lista de URLs para monitoramento
PRODUCT_URLS = [
    'https://www.mercadolivre.com.br/carrinho-beb-napoli-beb-conforto-e-base-galzerano/p/MLB32171624',
    'https://produto.mercadolivre.com.br/MLB-1231793406-berco-cama-multifuncional-com-cama-auxiliar-3-gavetas-dewt-_JM'  # Substitua pelo URL real de outro produto
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
        return None

    soup = BeautifulSoup(html, 'html.parser')
    try:
        # Extrair o nome do produto
        product_name = soup.find('h1', class_='ui-pdp-title').get_text(strip=True)
        logging.debug(f"Nome do produto (debug): {product_name}")  # Debug no arquivo de log

        # Tentar encontrar preços de diferentes formas
        prices = soup.find_all('span', class_='andes-money-amount__fraction')
        logging.debug(f"Preços encontrados (debug): {len(prices)}")  # Debug no arquivo de log

        # Verifica a quantidade de preços encontrados
        if len(prices) < 2:
            logging.error(f"Não foi possível encontrar preços suficientes para o produto {product_name}. Preços encontrados: {len(prices)}")
            return None
        
        # Atribuir valores de preços
        new_price = int(prices[0].get_text(strip=True).replace('.', ''))  # Preço atual
        installment_price = int(prices[1].get_text(strip=True).replace('.', ''))  # Preço parcelado

        # Buscar o preço original (se existir)
        old_price_tag = soup.find('span', class_='andes-price__original-value')
        old_price = None
        if old_price_tag:
            old_price = int(old_price_tag.get_text(strip=True).replace('.', ''))

        # Pegar o timestamp de agora
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        
    except AttributeError as e:
        logging.error(f"Erro ao parsear HTML: {e}")
        return None

    # Verifica se o preço atual foi encontrado
    if not new_price:
        logging.error(f"Preço atual não encontrado para o produto {product_name}.")
        return None

    # Salva as informações no arquivo de log
    logging.debug(f"Dados extraídos (debug): {product_name}, {new_price}, {old_price}, {installment_price}")  # Debug no arquivo de log

    # Exibe as informações no terminal
    logging.info(f"Produto: {product_name} | Preço Atual: {new_price} | Preço Antigo: {old_price if old_price else 'N/A'} | Preço Parcelado: {installment_price} | Timestamp: {timestamp}")

    return {
        'product_name': product_name,
        'old_price': old_price if old_price else 0,  # Se não houver preço antigo, coloca 0
        'new_price': new_price,
        'installment_price': installment_price if installment_price else 0,  # Se não houver preço parcelado, coloca 0
        'timestamp': timestamp
    }

# Exemplo de uso
html_content = "<html>Seu HTML aqui</html>"  # Substitua pelo conteúdo da página HTML
product_info = parse_page(html_content)




def create_connection(db_name='CarrinhoDoJoaodb'):
    """Cria uma conexão com o banco de dados SQLite."""
    conn = sqlite3.connect(db_name)
    return conn

def setup_database(conn):
    """Cria a tabela de preços se ela não existir."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            old_price INTEGER,
            new_price INTEGER,
            installment_price INTEGER,
            timestamp TEXT
        )
    ''')
    conn.commit()

def save_to_database(conn, data):
    """Salva uma linha de dados no banco de dados SQLite usando pandas."""
    if not data:
        logging.warning("Nenhum dado para salvar no banco de dados.")
        return
    df = pd.DataFrame([data])
    df.to_sql('prices', conn, if_exists='append', index=False)

def get_max_price(conn, product_name):
    """Consulta o maior preço registrado para um produto específico."""
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(new_price), timestamp FROM prices WHERE product_name = ?", (product_name,))
    result = cursor.fetchone()
    if result and result[0] is not None:
        return result[0], result[1]
    return None, None

async def send_telegram_message(product_name, current_price, max_price, max_price_timestamp):
    """Envia uma mensagem para o Telegram."""
    try:
        message = (
            f"📊 *Monitoramento de Preços:*\n\n"
            f"Produto: *{product_name}*\n"
            f"Preço Atual: R$ {current_price}\n"
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
    interval = 60  # Intervalo inicial em segundos

    try:
        while True:
            for url in PRODUCT_URLS:
                # Faz a requisição e parseia a página
                page_content = fetch_page(url)
                product_info = parse_page(page_content)

                if not product_info:
                    logging.warning("Falha ao obter informações do produto. Tentando novamente...")
                    continue

                current_price = product_info['new_price']
                product_name = product_info['product_name']
                max_price, max_price_timestamp = get_max_price(conn, product_name)

                # Comparação de preços e envio de notificação
                await send_telegram_message(product_name, current_price, max_price, max_price_timestamp)

                # Salva os dados no banco de dados SQLite
                save_to_database(conn, product_info)
                logging.info("Dados salvos no banco: %s", product_info)

            # Aguarda antes da próxima execução
            await asyncio.sleep(interval)

    except KeyboardInterrupt:
        logging.info("Parando a execução...")
    finally:
        conn.close()

# Executa o loop assíncrono
if __name__ == '__main__':
    asyncio.run(main())
