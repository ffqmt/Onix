import os
import glob
from pathlib import Path


def verificar_arquivos_pdf_crdownload(caminho_pasta):
    """
    Verifica se há arquivos .pdf.crdownload na pasta especificada
    e retorna suas localizações
    """

    # Caminho da pasta
    pasta = r"C:\Onix\Onix\OnixWeb\rpautomation\transactionFiles\1a26d28027f2dd6eeea52154659736073d6e763a123a2caaa4c66027e449aa8b"

    print(f"🔍 Verificando pasta: {pasta}")
    print("-" * 80)

    # Verificar se a pasta existe
    if not os.path.exists(pasta):
        print("❌ ERRO: A pasta especificada não existe!")
        return

    # Usar pathlib para melhor manipulação de caminhos
    pasta_path = Path(pasta)

    # Procurar por arquivos .pdf.crdownload recursivamente
    arquivos_encontrados = []

    try:
        # Buscar recursivamente usando pathlib
        arquivos_encontrados = list(pasta_path.rglob("*.pdf.crdownload"))
    except Exception as e:
        print(f"❌ Erro ao buscar arquivos: {e}")
        return

    if arquivos_encontrados:
        print(f"✅ Encontrados {len(arquivos_encontrados)} arquivo(s) .pdf.crdownload:")
        print()

        # Contar arquivos por pasta para resumo
        pastas_count = {}

        for i, arquivo_path in enumerate(arquivos_encontrados, 1):
            try:
                # Usar pathlib para operações mais seguras
                arquivo_str = str(arquivo_path)
                pasta_pai = str(arquivo_path.parent)
                nome_arquivo = arquivo_path.name

                # Contar por pasta
                pastas_count[pasta_pai] = pastas_count.get(pasta_pai, 0) + 1

                # Tentar obter tamanho do arquivo de forma segura
                try:
                    tamanho = arquivo_path.stat().st_size
                    tamanho_mb = tamanho / (1024 * 1024)
                    info_tamanho = f"{tamanho:,} bytes ({tamanho_mb:.2f} MB)"
                except (OSError, FileNotFoundError) as e:
                    info_tamanho = "❌ Não foi possível acessar o arquivo"

                print(f"📄 Arquivo {i}:")
                print(f"   📝 Nome: {nome_arquivo}")
                print(f"   📏 Tamanho: {info_tamanho}")
                print(f"   📁 Pasta: {pasta_pai}")

                # Verificar se o caminho é muito longo
                if len(arquivo_str) > 260:
                    print(f"   ⚠️  AVISO: Caminho muito longo ({len(arquivo_str)} caracteres)")

                print()

            except Exception as e:
                print(f"❌ Erro ao processar arquivo {i}: {e}")
                print(f"   📍 Caminho: {arquivo_path}")
                print()

        # Mostrar resumo por pasta
        print("📊 RESUMO POR PASTA:")
        print("-" * 50)
        for pasta, count in sorted(pastas_count.items()):
            # Mostrar caminho relativo para melhor legibilidade
            try:
                pasta_relativa = os.path.relpath(pasta, pasta)
                if pasta_relativa == ".":
                    pasta_relativa = "Pasta raiz"
            except:
                pasta_relativa = pasta

            print(f"📁 {count} arquivo(s) em: {pasta}")

    else:
        print("❌ Nenhum arquivo .pdf.crdownload encontrado na pasta especificada.")

        # Verificar se há outros tipos de arquivo para contexto
        print("\n🔍 Verificando outros arquivos na pasta...")
        verificar_outros_arquivos(pasta_path)


def verificar_outros_arquivos(pasta_path):
    """
    Verifica outros tipos de arquivo na pasta
    """
    try:
        todos_arquivos = list(pasta_path.rglob("*"))
        arquivos_apenas = [f for f in todos_arquivos if f.is_file()]

        if arquivos_apenas:
            print(f"📋 Total de arquivos encontrados na pasta: {len(arquivos_apenas)}")

            # Mostrar tipos de arquivo presentes
            extensoes = {}
            for arquivo in arquivos_apenas:
                ext = arquivo.suffix.lower()
                if ext:
                    extensoes[ext] = extensoes.get(ext, 0) + 1

            if extensoes:
                print("\n📊 Tipos de arquivo presentes:")
                for ext, count in sorted(extensoes.items()):
                    print(f"   {ext}: {count} arquivo(s)")

                # Destacar se há arquivos .crdownload de outros tipos
                crdownload_outros = [ext for ext in extensoes.keys() if ext.endswith('.crdownload')]
                if crdownload_outros:
                    print(f"\n⚠️  Outros arquivos .crdownload encontrados: {', '.join(crdownload_outros)}")
        else:
            print("📭 Nenhum arquivo encontrado na pasta.")

    except Exception as e:
        print(f"❌ Erro ao verificar outros arquivos: {e}")


def verificar_downloads_incompletos():
    """
    Função adicional para verificar downloads incompletos em locais comuns
    """
    print("\n" + "=" * 80)
    print("🔍 VERIFICAÇÃO ADICIONAL - Downloads incompletos em locais comuns:")
    print("=" * 80)

    # Locais comuns onde downloads incompletos podem estar
    locais_comuns = [
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path("C:/Temp"),
        Path("C:/Windows/Temp")
    ]

    for local in locais_comuns:
        if local.exists():
            try:
                crdownloads = list(local.glob("*.crdownload"))
                if crdownloads:
                    print(f"\n📁 {local}:")
                    for arquivo in crdownloads:
                        print(f"   📄 {arquivo.name}")
            except Exception as e:
                print(f"❌ Erro ao verificar {local}: {e}")


def listar_caminhos_longos(pasta_path, limite=250):
    """
    Lista arquivos com caminhos muito longos
    """
    print(f"\n🔍 Verificando caminhos longos (>{limite} caracteres):")
    print("-" * 50)

    caminhos_longos = []
    try:
        for arquivo in pasta_path.rglob("*"):
            if arquivo.is_file() and len(str(arquivo)) > limite:
                caminhos_longos.append(arquivo)

        if caminhos_longos:
            print(f"⚠️  Encontrados {len(caminhos_longos)} arquivo(s) com caminhos longos:")
            for arquivo in caminhos_longos[:10]:  # Mostrar apenas os primeiros 10
                print(f"   📄 {arquivo.name} ({len(str(arquivo))} chars)")
                print(f"      📁 {arquivo.parent}")

            if len(caminhos_longos) > 10:
                print(f"   ... e mais {len(caminhos_longos) - 10} arquivo(s)")
        else:
            print("✅ Nenhum caminho excessivamente longo encontrado.")

    except Exception as e:
        print(f"❌ Erro ao verificar caminhos longos: {e}")


# Executar a verificação
if __name__ == "__main__":
    pasta_principal = Path(
        r"C:\Onix\Onix\OnixWeb\rpautomation\transactionFiles\1a26d28027f2dd6eeea52154659736073d6e763a123a2caaa4c66027e449aa8b")

    verificar_arquivos_pdf_crdownload("")
    verificar_downloads_incompletos()
    listar_caminhos_longos(pasta_principal)

    print("\n" + "=" * 80)
    print("💡 DICAS:")
    print("• Arquivos .crdownload são downloads incompletos do Chrome")
    print("• 71 arquivos .crdownload indicam muitos downloads interrompidos")
    print("• Caminhos muito longos podem causar problemas no Windows")
    print("• Considere mover ou renomear arquivos para caminhos mais curtos")
    print("=" * 80)