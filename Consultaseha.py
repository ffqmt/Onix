import os
import re
import sqlite3
from pathlib import Path

# ==========================================
# CONFIGURAÇÕES
# ==========================================
# Caminho do banco de dados SQLite do Onix
DB_PATH = r"C:\Onix\Onix\OnixWeb\onixTestDB.sqlite3" # Ajuste para o caminho real do seu arquivo .db

# Caminho raiz do OneDrive
DIR_ROOT = r"F:\contaudi\OneDrive - CONTAUDI ASSESSORIA CONTABIL LTDA\Documentos - CONTAUDI ASSESSORIA CONTABIL LTDA\Contaudi - Onedrive\Clientes"
ANO = "2026"
MES_ATUAL = "07"  # Junho (Mês de análise)

# Mapeamento de processos: Nome do Processo -> Coluna no Banco de Dados e Arquivos Esperados
DICIONARIO_PROCESSOS = {
 "NFe Saída": {
  "coluna_db": "sefaz_nfe_saida",
  "com_movimento": ["Sefaz-Saidas.xls", "Sefaz-Saidas.xlsx"],
  "sem_movimento": ["NFe-Sem-Saidas.png", "NFe-Sem-Saida e Entrada.png"],
  "aplica_pf": True
 },
 "NFe Entrada": {
  "coluna_db": "sefaz_nfe_entrada",
  "com_movimento": ["Sefaz-Entradas.xls", "Sefaz-Entradas.xlsx"],
  "sem_movimento": ["NFe-Sem-Entradas.png", "NFe-Sem-Saida e Entrada.png"],
  "aplica_pf": True
 },
 "CT-e Emissor": {
  "coluna_db": "sefaz_cte_emitido",
  "com_movimento": ["CT-e Emissor.xlsx", "CT-e Emissor.xls"],
  "sem_movimento": ["CTe-Sem-Emissoes.png", "CTe-Sem Emissor e Tomador.png"],
  "aplica_pf": True
 },
 "CT-e Tomador": {
  "coluna_db": "sefaz_cte_tomado",
  "com_movimento": ["CT-e Tomador.xlsx", "CT-e Tomador.xls"],
  "sem_movimento": ["CTe-Sem-Tomados.png", "CTe-Sem Emissor e Tomador.png"],
  "aplica_pf": True
 },
 "NFC-e Emitida": {
  "coluna_db": "sefaz_nfce",
  "com_movimento": ["NFCe Emitidas.xls", "NFCe Emitidas.xlsx"],
  "sem_movimento": ["NFCe-Sem Emissoes.png"],
  "aplica_pf": False  # REGRA: Pessoa Física (Rural) NÃO emite NFC-e
 }
}


def normalizar_nome(nome):
 nome = nome.lower()
 nome = re.sub(r'[áàâãä]', 'a', nome)
 nome = re.sub(r'[éèêë]', 'e', nome)
 nome = re.sub(r'[íìîï]', 'i', nome)
 nome = re.sub(r'[óòôõö]', 'o', nome)
 nome = re.sub(r'[úùûü]', 'u', nome)
 nome = re.sub(r'[ç]', 'c', nome)
 return re.sub(r'\s+', ' ', nome).strip()


def carregar_clientes_do_banco():
 """Conecta ao SQLite e busca todas as empresas ativas (PJ e PF)."""
 if not Path(DB_PATH).exists():
  print(f"❌ ERRO: Banco de dados não encontrado em: {DB_PATH}")
  return {}

 conn = sqlite3.connect(DB_PATH)
 cursor = conn.cursor()

 # Query unificada filtrando estritamente por active = 1 (Regra do Robô)
 query = """
    SELECT 
        id, id_empresa, name, cnpj_cpf, ie, 
        sefaz_nfe_saida, sefaz_nfe_entrada, sefaz_cte_emitido, sefaz_cte_tomado, sefaz_nfce,
        'PJ' as tipo
    FROM PessoaJuridica
    WHERE active = 1

    UNION ALL

    SELECT 
        id, id_empresa, name, cnpj_cpf, ie, 
        sefaz_nfe_saida, sefaz_nfe_entrada, sefaz_cte_emitido, sefaz_cte_tomado, sefaz_nfce,
        'PF' as tipo
    FROM PessoaFisica
    WHERE active = 1
    """

 try:
  cursor.execute(query)
  linhas = cursor.fetchall()
  colunas = [col[0] for col in cursor.description]

  clientes = []
  for linha in linhas:
   clientes.append(dict(zip(colunas, linha)))

  print(f"✅ {len(clientes)} clientes ativos carregados do banco de dados (Onix).")
  return clientes
 except Exception as e:
  print(f"❌ Erro ao ler banco de dados: {e}")
  return {}
 finally:
  conn.close()


def encontrar_pasta_cliente(nome_banco, raiz_path):
 """
 Tenta associar o nome do banco com a pasta física no OneDrive.
 Usa normalização para evitar que diferenças de acento/espaço quebrem o vínculo.
 """
 nome_banco_norm = normalizar_nome(nome_banco)

 for pasta in raiz_path.iterdir():
  if not pasta.is_dir() or pasta.name.startswith((".", "~")):
   continue

  # Se o nome normalizado da pasta contiver ou for igual ao nome do banco
  if nome_banco_norm in normalizar_nome(pasta.name):
   return pasta

 return None


def obter_caminho_relatorios(pasta_cliente, tipo_cliente, ano, mes):
 """Retorna o caminho de relatórios baseado no tipo de cliente."""
 if tipo_cliente == 'PF':
  return pasta_cliente / "RURAL" / ano / mes / "Relatórios"
 else:
  return pasta_cliente / "FISCAL PJ" / ano / mes / "Relatórios"


def verificar_presenca_no_mes(caminho_pasta, arquivos_esperados):
 if not caminho_pasta or not caminho_pasta.exists():
  return False, None, None

 arquivos = [normalizar_nome(f.name) for f in caminho_pasta.iterdir() if f.is_file()]

 # 1. Com movimento
 for arq_com in arquivos_esperados["com_movimento"]:
  arq_com_norm = normalizar_nome(arq_com)
  if any(arq_com_norm in arq for arq in arquivos):
   return True, "✅ OK - Com Movimento", arq_com

 # 2. Sem movimento
 for arq_sem in arquivos_esperados["sem_movimento"]:
  arq_sem_norm = normalizar_nome(arq_sem)
  if any(arq_sem_norm in arq for arq in arquivos):
   return True, "ℹ️  OK - Sem Movimento", arq_sem

 return False, None, None


def auditar(filtro_processo=None):
 raiz = Path(DIR_ROOT)
 if not raiz.exists():
  print(f"❌ Erro: Pasta raiz do OneDrive não encontrada em: {DIR_ROOT}")
  return

 # 1. Carrega dados reais do banco
 clientes_db = carregar_clientes_do_banco()
 if not clientes_db:
  print("Abortando auditoria por falta de dados do banco.")
  return

 print("\n" + "=" * 90)
 print(f" AUDITORIA INTEGRADA ONIX/ONEDRIVE - COMPETÊNCIA {MES_ATUAL}/{ANO}")
 if filtro_processo:
  print(f" FOCADO APENAS EM: {filtro_processo}")
 print("=" * 90)

 total_analisados = 0
 total_faltando = 0
 lista_reprocessar = []  # Armazena tuplas (id, nome, tipo, processo)

 for cli in clientes_db:
  nome_empresa = cli["name"]
  tipo_cliente = cli["tipo"]
  id_empresa = cli["id_empresa"]
  id_registro = cli["id"]  # ID da tabela PessoaJuridica ou PessoaFisica

  # Buscar pasta física correspondente no OneDrive
  pasta_cliente = encontrar_pasta_cliente(nome_empresa, raiz)

  if not pasta_cliente:
   print(f"\n⚠️  [NÃO ENCONTRADA] 🏢 {nome_empresa} ({tipo_cliente})")
   print("     -> Pasta do cliente não foi localizada no OneDrive pelo nome.")
   # Adiciona como falha geral (Pasta não criada)
   lista_reprocessar.append((id_registro, nome_empresa, tipo_cliente, "Pasta não criada (Rodar todos)"))
   total_faltando += 1
   continue

  caminho_atual = obter_caminho_relatorios(pasta_cliente, tipo_cliente, ANO, MES_ATUAL)
  total_analisados += 1

  print(f"\n🏢 {nome_empresa} [{tipo_cliente}]")

  # Se a pasta do mês atual nem existe fisicamente
  if not caminho_atual or not caminho_atual.exists():
   print(f"  ❌ Pasta de relatórios do mês atual não criada no OneDrive: {caminho_atual}")
   lista_reprocessar.append((id_registro, nome_empresa, tipo_cliente, "Pasta não criada (Rodar todos)"))
   total_faltando += 1
   continue

  # Processos a analisar
  processos_alvo = [filtro_processo] if filtro_processo else DICIONARIO_PROCESSOS.keys()

  for proc in processos_alvo:
   config_proc = DICIONARIO_PROCESSOS[proc]
   coluna_db = config_proc["coluna_db"]

   # REGRA DE SEGURANÇA: Se for Pessoa Física (PF) e o processo não se aplica a PF
   if tipo_cliente == 'PF' and not config_proc.get("aplica_pf", True):
    print(f"  [⏭️  DISPENSADO] {proc:<15} (Pessoa Física/Rural não emite NFC-e)")
    continue

   # Regra de Ouro: O banco de dados diz se o processo deve rodar para esta empresa!
   deve_rodar = cli.get(coluna_db, 0)

   if deve_rodar != 1:
    print(f"  [⏭️  DISPENSADO] {proc:<15} (Desabilitado no cadastro do Onix)")
    continue

   # Verificar se o arquivo físico existe no OneDrive
   existe_atual, status_atual, arq_atual = verificar_presenca_no_mes(caminho_atual, config_proc)

   if existe_atual:
    print(f"  [{status_atual}] {proc:<15} {f'({arq_atual})' if arq_atual else ''}")
   else:
    print(f"  [❌ FALTANDO] {proc:<15}")
    lista_reprocessar.append((id_registro, nome_empresa, tipo_cliente, proc))
    total_faltando += 1

 # ==========================================
 # RESUMO DA REEXECUÇÃO & COMANDOS SQL
 # ==========================================
 print("\n" + "=" * 90)
 print(f" RESUMO DE REEXECUÇÃO - ENVIAR PARA O ONIX")
 print("=" * 90)
 if not lista_reprocessar:
  print("  🎉 Tudo 100% em dia! Nenhuma empresa precisa rodar novamente.")
 else:
  resumo_agrupado = {}
  sql_updates_pj = []
  sql_updates_pf = []

  for id_reg, emp, tipo, proc in lista_reprocessar:
   if (emp, tipo) not in resumo_agrupado:
    resumo_agrupado[(emp, tipo)] = []
   resumo_agrupado[(emp, tipo)].append(proc)

   if tipo == 'PJ':
    sql_updates_pj.append(str(id_reg))
   else:
    sql_updates_pf.append(str(id_reg))

  for (emp, tipo), procs in resumo_agrupado.items():
   print(f" 🏢 {emp} ({tipo})")
   print(f"    -> Rodar: {', '.join(procs)}")

  print("\n" + "=" * 90)
  print(f" 💻 COMANDOS SQL PARA FORÇAR REEXECUÇÃO NO ONIX")
  print("=" * 90)
  print("Execute estes comandos no seu gerenciador SQLite para resetar os clientes pendentes:")

  if sql_updates_pj:
   ids_pj = ", ".join(sql_updates_pj)
   print(f"\n-- Para Pessoas Jurídicas (PJ):")
   print(f"UPDATE PessoaJuridica SET finished_mensal = 0, active_mensal = 1 WHERE id IN ({ids_pj}) AND active = 1;")

  if sql_updates_pf:
   ids_pf = ", ".join(sql_updates_pf)
   print(f"\n-- Para Pessoas Físicas (PF/Rural):")
   print(f"UPDATE PessoaFisica SET finished_mensal = 0, active_mensal = 1 WHERE id IN ({ids_pf}) AND active = 1;")

 print(f"\nTotal analisados: {total_analisados} | Pendências reais encontradas: {total_faltando}")
 print("=" * 90)


if __name__ == "__main__":
 print("Selecione o tipo de análise:")
 print("1 - Auditoria Geral (Baseada no Banco de Dados Onix)")
 print("2 - Auditoria de NFC-e Emitida")
 print("3 - Auditoria de CT-e (Emissor e Tomador)")
 print("4 - Auditoria de NF-e (Saídas e Entradas)")

 opcao = input("Opção: ").strip()

 if opcao == '1':
  auditar()
 elif opcao == '2':
  auditar(filtro_processo="NFC-e Emitida")
 elif opcao == '3':
  print("\nExecutando auditoria para CT-e Emissor...")
  auditar(filtro_processo="CT-e Emissor")
  print("\nExecutando auditoria para CT-e Tomador...")
  auditar(filtro_processo="CT-e Tomador")
 elif opcao == '4':
  print("\nExecutando auditoria para NFe Saída...")
  auditar(filtro_processo="NFe Saída")
  print("\nExecutando auditoria para NFe Entrada...")
  auditar(filtro_processo="NFe Entrada")
 else:
  print("Opção inválida.")