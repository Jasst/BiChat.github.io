import requests

# Публичный URL первого сервера
server1_url = 'https://jasstme.pythonanywhere.com'
# Публичный URL второго сервера
server2_url = 'https://eb56-2a03-d000-1505-ad22-dce6-5f86-f134-e5f.ngrok-free.app'


def register_peer(server_url, peer_url):
    try:
        response = requests.post(f'{server_url}/register_peer', json={'peer': peer_url})
        response.raise_for_status()
        print(f"Register peer on {server_url}: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"Error registering peer {peer_url} on {server_url}: {e}")
        print(f"Response content: {response.content}")


def sync_chain(target_server_url, source_server_url):
    try:
        response = requests.get(f'{source_server_url}/chain')
        response.raise_for_status()
        peer_chain = response.json().get('chain')
        if peer_chain:
            response = requests.post(f'{target_server_url}/sync_chain', json={'chain': peer_chain})
            response.raise_for_status()
            print(f"Sync chain of {target_server_url} with {source_server_url}: {response.json()}")
        else:
            print(f"No chain data received from {source_server_url}")
    except requests.exceptions.RequestException as e:
        print(f"Error syncing chain from {source_server_url} to {target_server_url}: {e}")
        print(f"Response content: {response.content}")


# Регистрация первого сервера на втором
register_peer(server2_url, server1_url)

# Регистрация второго сервера на первом
register_peer(server1_url, server2_url)

# Синхронизация цепочки первого сервера со вторым
sync_chain(server1_url, server2_url)

# Синхронизация цепочки второго сервера с первым
sync_chain(server2_url, server1_url)
