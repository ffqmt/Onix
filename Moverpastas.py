import os
import shutil
import re
from pathlib import Path

# ===================== CONFIGURAÇÃO =====================
ORIGEM_BASE = Path(r"C:\Users\contaudi\OneDrive - CONTAUDI ASSESSORIA CONTABIL LTDA\Área de Trabalho\Prestados")
DESTINO_BASE = Path(r"C:\Users\contaudi\OneDrive - CONTAUDI ASSESSORIA CONTABIL LTDA\Documentos - CONTAUDI ASSESSORIA CONTABIL LTDA\Contaudi - Onedrive\Clientes")

# Se quiser limitar a anos/meses específicos:
MOVER_APENAS_MESES_ESPECIFICOS = False
ANOS_MESES_PERMITIDOS = {("2025", "12")}

# Se True, remove pastas vazias na origem depois de mover:
REMOVER_ORIGEM_VAZIA = True

# Testar sem executar (não move nada, só mostra o que faria):
DRY_RUN = False

# Remove o último bloco se ele for somente números? (ex: CNPJ / inscrição / ID)
REMOVER_SUFIXO_NUMERICO = True

# Critérios para considerar a última parte como “sufixo identificador numérico”
TAMANHO_MIN_SUFIXO = 5      # evita remover números muito curtos tipo "1" ou "22"
TAMANHO_MAX_SUFIXO = 20     # limite superior de segurança

# ========================================================

CODIGO_REGEX = re.compile(r"^(\d+)")
SEPARADOR_PARTES = " - "

def extrair_codigo(nome_pasta: str) -> str | None:
    m = CODIGO_REGEX.match(nome_pasta.strip())
    return m.group(1) if m else None

def normalizar_nome_cliente(nome_pasta: str) -> str:
    """
    Mantém todas as partes, exceto remove a última se for bloco numérico plausível (CNPJ / inscrição etc).
    Ex:
      '295 - MELINA BEE PERERA - FAZENDA SUSPIRO - 132435195'
         -> '295 - MELINA BEE PERERA - FAZENDA SUSPIRO'
    """
    partes = [p.strip() for p in nome_pasta.split(SEPARADOR_PARTES)]
    if len(partes) < 2:
        return nome_pasta.strip()

    if REMOVER_SUFIXO_NUMERICO:
        ultima = partes[-1]
        if ultima.isdigit() and TAMANHO_MIN_SUFIXO <= len(ultima) <= TAMANHO_MAX_SUFIXO:
            partes = partes[:-1]

    # Recompõe com o mesmo separador
    return SEPARADOR_PARTES.join(partes)

def listar_clientes(origem: Path):
    return [p for p in origem.iterdir() if p.is_dir()]

def obter_estruturas_ano_mes(pasta_cliente: Path):
    """
    Retorna lista de tuplas (ano, mes, caminho_da_pasta_mes)
    """
    estruturas = []
    for ano_dir in sorted(pasta_cliente.iterdir()):
        if ano_dir.is_dir() and ano_dir.name.isdigit() and len(ano_dir.name) == 4:
            for mes_dir in sorted(ano_dir.iterdir()):
                if mes_dir.is_dir() and mes_dir.name.isdigit() and len(mes_dir.name) == 2:
                    try:
                        mes_int = int(mes_dir.name)
                        if not (1 <= mes_int <= 12):
                            continue
                    except ValueError:
                        continue
                    estruturas.append((ano_dir.name, mes_dir.name, mes_dir))
    return estruturas

def mover_conteudo(origem_mes: Path, destino_final: Path):
    """
    Move todos os itens (arquivos e pastas) de origem_mes para destino_final.
    Se houver conflito de nome, o destino é substituído.
    """
    itens = list(origem_mes.iterdir())
    movidos = 0
    for item in itens:
        destino_item = destino_final / item.name
        if DRY_RUN:
            print(f"[DRY-RUN] moveria: {item} -> {destino_item}")
        else:
            if destino_item.exists():
                if destino_item.is_file():
                    destino_item.unlink()
                else:
                    shutil.rmtree(destino_item)
            shutil.move(str(item), str(destino_item))
        movidos += 1
    return movidos

def remover_pastas_vazias(caminho: Path):
    """
    Remove recursivamente pastas vazias.
    """
    if not caminho.exists() or not caminho.is_dir():
        return
    for sub in caminho.iterdir():
        if sub.is_dir():
            remover_pastas_vazias(sub)
    try:
        if not any(caminho.iterdir()):
            if DRY_RUN:
                print(f"[DRY-RUN] removeria pasta vazia: {caminho}")
            else:
                caminho.rmdir()
    except Exception:
        pass

def processar():
    if not ORIGEM_BASE.exists():
        print(f"Origem não encontrada: {ORIGEM_BASE}")
        return
    if not DESTINO_BASE.exists():
        print(f"Destino não encontrado: {DESTINO_BASE}")
        return

    clientes = listar_clientes(ORIGEM_BASE)
    if not clientes:
        print("Nenhuma pasta de cliente encontrada na origem.")
        return

    total_clientes = 0
    total_estruturas = 0
    total_movidas = 0
    sem_codigo = 0
    sem_estruturas = 0

    print(f"=== INÍCIO (DRY_RUN={DRY_RUN}) ===")
    print(f"Origem:   {ORIGEM_BASE}")
    print(f"Destino:  {DESTINO_BASE}")
    print(f"Clientes encontrados: {len(clientes)}")
    print(f"Regra de normalização: remover sufixo numérico? {REMOVER_SUFIXO_NUMERICO}\n")

    for cliente_dir in clientes:
        nome_original = cliente_dir.name
        codigo = extrair_codigo(nome_original)
        if not codigo:
            print(f"[IGNORADO] Sem código no nome: {nome_original}")
            sem_codigo += 1
            continue

        nome_normalizado = normalizar_nome_cliente(nome_original)
        estruturas = obter_estruturas_ano_mes(cliente_dir)

        if not estruturas:
            print(f"[SEM ESTRUTURA] {nome_original}")
            sem_estruturas += 1
            continue

        total_clientes += 1
        print(f"\nCliente origem: {nome_original}")
        print(f"Cliente destino normalizado: {nome_normalizado}")
        print(f"Estruturas Ano/Mês: {len(estruturas)}")

        for ano, mes, pasta_mes in estruturas:
            if MOVER_APENAS_MESES_ESPECIFICOS and (ano, mes) not in ANOS_MESES_PERMITIDOS:
                print(f"  - Pulando {ano}/{mes} (não permitido)")
                continue

            destino_final = DESTINO_BASE / nome_normalizado / "Rural" / ano / mes
            total_estruturas += 1

            if DRY_RUN:
                print(f"[DRY-RUN] Criaria destino: {destino_final}")
            else:
                destino_final.mkdir(parents=True, exist_ok=True)

            qtd_itens_origem = len(list(pasta_mes.iterdir()))
            print(f"  - Movendo {ano}/{mes} ({qtd_itens_origem} itens) -> {destino_final}")

            movidos = mover_conteudo(pasta_mes, destino_final)
            total_movidas += movidos

            if REMOVER_ORIGEM_VAZIA:
                remover_pastas_vazias(pasta_mes.parent)  # limpa mês e talvez ano

    print("\n=== RESUMO FINAL ===")
    print(f"Clientes processados:              {total_clientes}")
    print(f"Estruturas Ano/Mês tratadas:       {total_estruturas}")
    print(f"Itens movidos (arquivos/pastas):   {total_movidas}")
    print(f"Pastas sem código:                 {sem_codigo}")
    print(f"Pastas sem estrutura Ano/Mês:      {sem_estruturas}")
    print(f"DRY-RUN:                           {DRY_RUN}")
    print(f"Remoção de sufixo numérico ativa:  {REMOVER_SUFIXO_NUMERICO}")
    print("===================================")

if __name__ == "__main__":
    processar()
