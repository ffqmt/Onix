from pathlib import Path
from datetime import datetime
import csv
import shutil

# ============================================================
# CONFIGURAÇÕES
# ============================================================

# Caminho do CSV gerado pelo script de análise.
# Coloque aqui o nome/caminho exato do arquivo de suspeitos.
ARQUIVO_SUSPEITOS = Path(
    r"suspeitos_mover_fiscalpj_para_rural_2026_05_2026-06-03_08-15-13.csv"
)

# Comece com True.
# True  = só simula, NÃO move nada.
# False = move de verdade.
DRY_RUN = False

# Se destino já existir:
# - False: não move e marca como bloqueado.
# - True: tenta mesclar conteúdo da origem dentro do destino.
#
# Minha recomendação inicial: deixar False.
PERMITIR_MESCLAR_SE_DESTINO_EXISTIR = False

# Se depois de mover a pasta 05, a pasta FISCAL PJ\2026 ficar vazia,
# o script pode remover a pasta do ano e depois FISCAL PJ se também ficar vazia.
REMOVER_FISCAL_PJ_VAZIO_DEPOIS = False

# Delimitador do CSV.
# Pelo script anterior, usamos ";"
DELIMITADOR_CSV = ";"

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def pasta_tem_conteudo(pasta: Path) -> bool:
    if not pasta.exists() or not pasta.is_dir():
        return False

    try:
        return any(pasta.rglob("*"))
    except Exception:
        return True


def pasta_esta_vazia(pasta: Path) -> bool:
    if not pasta.exists() or not pasta.is_dir():
        return False

    try:
        return not any(pasta.iterdir())
    except Exception:
        return False


def contar_itens_recursivo(pasta: Path) -> int:
    if not pasta.exists():
        return 0

    try:
        return sum(1 for _ in pasta.rglob("*"))
    except Exception:
        return -1


def detectar_delimitador(caminho_csv: Path) -> str:
    """
    Tenta detectar se o CSV está separado por ;, tab ou vírgula.
    """
    try:
        texto = caminho_csv.read_text(encoding="utf-8-sig", errors="ignore")
        primeira_linha = texto.splitlines()[0] if texto.splitlines() else ""

        if "\t" in primeira_linha:
            return "\t"
        if ";" in primeira_linha:
            return ";"
        return ","
    except Exception:
        return DELIMITADOR_CSV


def mover_pasta_inteira(origem: Path, destino: Path):
    """
    Move a pasta inteira origem para destino.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), str(destino))


def mesclar_pastas(origem: Path, destino: Path):
    """
    Move o conteúdo da origem para dentro do destino.
    Não sobrescreve arquivos existentes; se houver conflito, renomeia.
    Depois tenta remover a origem.
    """
    destino.mkdir(parents=True, exist_ok=True)

    for item in origem.iterdir():
        destino_item = destino / item.name

        if not destino_item.exists():
            shutil.move(str(item), str(destino_item))
        else:
            novo_destino = gerar_nome_sem_conflito(destino_item)
            shutil.move(str(item), str(novo_destino))

    try:
        origem.rmdir()
    except OSError:
        pass


def gerar_nome_sem_conflito(caminho: Path) -> Path:
    """
    Se destino já existir, gera:
    arquivo__CONFLITO_001.ext
    pasta__CONFLITO_001
    """
    pai = caminho.parent
    stem = caminho.stem
    suffix = caminho.suffix

    for i in range(1, 1000):
        candidato = pai / f"{stem}__CONFLITO_{i:03d}{suffix}"
        if not candidato.exists():
            return candidato

    raise RuntimeError(f"Não foi possível gerar nome sem conflito para: {caminho}")


def tentar_remover_pastas_vazias(origem_mes: Path):
    """
    Após mover FISCAL PJ\2026\05:
    - tenta remover FISCAL PJ\2026 se vazia;
    - tenta remover FISCAL PJ se vazia.
    """
    removidas = []

    pasta_ano = origem_mes.parent
    pasta_fiscal_pj = pasta_ano.parent

    for pasta in [pasta_ano, pasta_fiscal_pj]:
        if pasta.exists() and pasta.is_dir() and pasta_esta_vazia(pasta):
            try:
                pasta.rmdir()
                removidas.append(str(pasta))
            except Exception:
                pass

    return removidas


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def executar():
    if not ARQUIVO_SUSPEITOS.exists():
        print("ERRO: Arquivo CSV de suspeitos não encontrado:")
        print(ARQUIVO_SUSPEITOS.resolve())
        return

    delimitador = detectar_delimitador(ARQUIVO_SUSPEITOS)

    agora = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    arquivo_log = Path(f"log_movimento_fiscalpj_para_rural_{agora}.csv")

    total_linhas = 0
    total_movidos = 0
    total_simulados = 0
    total_bloqueados = 0
    total_erros = 0

    logs = []

    print("=" * 100)
    print("MOVIMENTAÇÃO DE FISCAL PJ PARA RURAL")
    print("=" * 100)
    print(f"Arquivo de entrada: {ARQUIVO_SUSPEITOS.resolve()}")
    print(f"Delimitador detectado: {repr(delimitador)}")
    print(f"Modo DRY_RUN: {DRY_RUN}")
    print(f"Permitir mesclar se destino existir: {PERMITIR_MESCLAR_SE_DESTINO_EXISTIR}")
    print("=" * 100)
    print()

    with ARQUIVO_SUSPEITOS.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=delimitador)

        colunas = reader.fieldnames or []

        if "origem_sugerida" not in colunas or "destino_sugerido" not in colunas:
            print("ERRO: O CSV precisa ter as colunas:")
            print("  origem_sugerida")
            print("  destino_sugerido")
            print()
            print("Colunas encontradas:")
            print(colunas)
            return

        for row in reader:
            total_linhas += 1

            origem = Path((row.get("origem_sugerida") or "").strip())
            destino = Path((row.get("destino_sugerido") or "").strip())
            status_original = (row.get("status") or "").strip()
            pasta_rural = (row.get("pasta_rural") or "").strip()
            pasta_fiscal_pj = (row.get("pasta_fiscal_pj") or "").strip()
            ano = (row.get("ano") or "").strip()
            mes = (row.get("mes_a_mover") or "").strip()
            empresa = ""

            # Tenta extrair empresa pelo caminho:
            try:
                empresa = origem.parents[2].name
            except Exception:
                empresa = ""

            acao = ""
            resultado = ""
            erro = ""
            origem_itens = contar_itens_recursivo(origem)

            print(f"[{total_linhas}] {empresa}")
            print(f"  Origem : {origem}")
            print(f"  Destino: {destino}")

            try:
                # ------------------------------------------------------------
                # VALIDAÇÕES
                # ------------------------------------------------------------

                if not origem:
                    acao = "BLOQUEADO"
                    resultado = "origem_vazia"
                    total_bloqueados += 1

                elif not destino:
                    acao = "BLOQUEADO"
                    resultado = "destino_vazio"
                    total_bloqueados += 1

                elif not origem.exists():
                    acao = "BLOQUEADO"
                    resultado = "origem_nao_existe"
                    total_bloqueados += 1

                elif not origem.is_dir():
                    acao = "BLOQUEADO"
                    resultado = "origem_nao_e_pasta"
                    total_bloqueados += 1

                elif destino.exists() and not PERMITIR_MESCLAR_SE_DESTINO_EXISTIR:
                    acao = "BLOQUEADO"
                    resultado = "destino_ja_existe"
                    total_bloqueados += 1

                elif origem.resolve() == destino.resolve():
                    acao = "BLOQUEADO"
                    resultado = "origem_igual_destino"
                    total_bloqueados += 1

                else:
                    # --------------------------------------------------------
                    # AÇÃO
                    # --------------------------------------------------------

                    if destino.exists() and PERMITIR_MESCLAR_SE_DESTINO_EXISTIR:
                        acao = "MESCLAR"
                    else:
                        acao = "MOVER"

                    if DRY_RUN:
                        resultado = "simulado_sem_mover"
                        total_simulados += 1
                    else:
                        if acao == "MESCLAR":
                            mesclar_pastas(origem, destino)
                        else:
                            mover_pasta_inteira(origem, destino)

                        removidas = []
                        if REMOVER_FISCAL_PJ_VAZIO_DEPOIS:
                            removidas = tentar_remover_pastas_vazias(origem)

                        resultado = "movido_com_sucesso"
                        if removidas:
                            resultado += " | pastas_vazias_removidas: " + " | ".join(removidas)

                        total_movidos += 1

            except Exception as e:
                acao = "ERRO"
                resultado = "erro_na_execucao"
                erro = repr(e)
                total_erros += 1

            print(f"  Ação    : {acao}")
            print(f"  Resultado: {resultado}")
            if erro:
                print(f"  Erro    : {erro}")
            print()

            logs.append({
                "empresa": empresa,
                "ano": ano,
                "mes": mes,
                "origem": str(origem),
                "destino": str(destino),
                "pasta_rural": pasta_rural,
                "pasta_fiscal_pj": pasta_fiscal_pj,
                "status_original": status_original,
                "origem_itens_recursivo": origem_itens,
                "acao": acao,
                "resultado": resultado,
                "erro": erro,
                "dry_run": str(DRY_RUN),
            })

    # ============================================================
    # SALVAR LOG
    # ============================================================

    with arquivo_log.open("w", newline="", encoding="utf-8-sig") as f:
        campos = [
            "empresa",
            "ano",
            "mes",
            "origem",
            "destino",
            "pasta_rural",
            "pasta_fiscal_pj",
            "status_original",
            "origem_itens_recursivo",
            "acao",
            "resultado",
            "erro",
            "dry_run",
        ]

        writer = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        writer.writeheader()
        writer.writerows(logs)

    print("=" * 100)
    print("RESUMO FINAL")
    print("=" * 100)
    print(f"Total de linhas processadas: {total_linhas}")
    print(f"Total simulados: {total_simulados}")
    print(f"Total movidos: {total_movidos}")
    print(f"Total bloqueados: {total_bloqueados}")
    print(f"Total erros: {total_erros}")
    print()
    print(f"Log gerado em:")
    print(f"  {arquivo_log.resolve()}")
    print("=" * 100)

    if DRY_RUN:
        print()
        print("ATENÇÃO: Rodou em DRY_RUN=True, então nada foi movido.")
        print("Confira o log. Se estiver tudo certo, altere DRY_RUN para False e rode novamente.")


if __name__ == "__main__":
    executar()
