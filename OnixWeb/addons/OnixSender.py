import socket
import os


def SendRPAData(zip_file_path, host, porta, pasta_destino_receiver):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        try:
            client_socket.connect((host, porta))

            # Envia o nome do arquivo ZIP como bytes
            zip_file_name = os.path.basename(zip_file_path).encode()
            client_socket.sendall(len(zip_file_name).to_bytes(4, byteorder='big'))
            client_socket.sendall(zip_file_name)

            # Envia o caminho do diretório de destino como bytes
            pasta_destino_receiver_bytes = pasta_destino_receiver.encode()
            client_socket.sendall(len(pasta_destino_receiver_bytes).to_bytes(4, byteorder='big'))
            client_socket.sendall(pasta_destino_receiver_bytes)

            # Aguarda a confirmação do servidor para enviar o conteúdo
            resposta_servidor = client_socket.recv(1024).decode()
            if resposta_servidor != 'PRONTO':
                print(f"Servidor não está pronto para receber o conteúdo. Resposta: {resposta_servidor}")
                return

            # Envia o conteúdo do arquivo ZIP
            with open(zip_file_path, 'rb') as zip_file:
                data = zip_file.read(1024)
                while data:
                    client_socket.sendall(data)
                    data = zip_file.read(1024)

            # Informa o servidor que a transmissão está concluída
            client_socket.sendall(b'FIM')

            # Aguarda a resposta do servidor
            resposta_servidor = client_socket.recv(1024).decode()
            print(resposta_servidor)
            return resposta_servidor

        except Exception as e:
            msg = f"Erro ao enviar arquivo ZIP: {e}"
            print(msg)
            return msg

        finally:
            # Fecha explicitamente a conexão
            client_socket.close()


# if __name__ == "__main__":
#     host_servidor = '191.223.125.126'  # substitua pelo endereço IP ou nome de host do Computador 2
#     porta_servidor = 5050
#     arquivo_zip_para_enviar = fr'D:\Onix Solutions\OnixWeb-Sender\arquivo.zip'  # substitua pelo caminho da pasta que você deseja enviar
#     # Novo parâmetro: caminho do diretório de destino no servidor
#     destino_servidor = r'C:\Users\phros\OneDrive\Área de Trabalho\ARQUIVOS RECEBIDOS'
#
#     SendRPAData(arquivo_zip_para_enviar, host_servidor, porta_servidor, destino_servidor)
