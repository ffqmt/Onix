import os
import re
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

try:
    from lxml import etree
except ImportError:
    etree = None
    print("[ERRO] Necessário lxml: pip install lxml")

# OCR / PDF
try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:
    pdf_extract_text = None

try:
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image
except Exception:
    pytesseract = None
    convert_from_path = None

# =========================
# CONFIGURAÇÕES
# =========================
BASE_CLIENTES = Path(r"C:\Users\contaudi\OneDrive - CONTAUDI ASSESSORIA CONTABIL LTDA\Documentos - CONTAUDI ASSESSORIA CONTABIL LTDA\Contaudi - Onedrive\Clientes")
ANO = "2025"
MES = "11"
SQLITE_DB = r"C:\Onix\Onix\OnixWeb\onixTestDB.sqlite3"

# Nomes das pastas
PASTA_RELATORIOS = "Relatórios"
PASTA_XML_PREST = "Relatórios\\XML - Prestados"
PASTA_XML_TOM = "Relatórios\\XML - Tomados"
PASTA_XML_CANCEL = "Relatórios\\XML- P. Canceladas"

# Arquivos candidatos à remoção quando cliente estiver "suspeito"
ARQS_CANDIDATOS = [
    "NFS-e - Tomados.pdf",
    "NFS-e - Prestados.pdf",
    "NOTAS - Emitidas.pdf",
    "NOTAS - Tomados.pdf",
]
PASTAS_CANDIDATAS = [
    "XML - Tomados",
    "XML - Prestados",
    "XML- P. Canceladas",
]

TARGET_FILES = {
    "Prestados": "NFS-e - Prestados",
    "Tomados": "NFS-e - Tomados",
}

ABRASF_NS = "http://www.abrasf.org.br/nfse.xsd"
NS = {"ns": ABRASF_NS}

# Regex cabeçalho
CNPJ_PATTERN = r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"
HEADER_CNPJ_LINE_RE = re.compile(r"CNPJ/CPF:\s*(" + CNPJ_PATTERN + ")", re.IGNORECASE)

# =========================
# UTILITÁRIOS
# =========================
def normalizar_doc(doc: str) -> str:
    return re.sub(r"\D", "", doc or "")

def diagnostico_sqlite(db_path: str) -> sqlite3.Connection | None:
    print(f"[CHECK] Caminho do SQLite: {db_path}")
    if not os.path.exists(db_path):
        print("[ERRO] Arquivo SQLite não existe.")
        return None
    print(f"[CHECK] Tamanho do arquivo: {os.path.getsize(db_path)} bytes")
    try:
        conn = sqlite3.connect(db_path)
    except Exception as e:
        print(f"[ERRO] Falha ao conectar no SQLite: {e}")
        return None
    return conn

def obter_cnpj_por_name(conn: sqlite3.Connection, name: str) -> str | None:
    cur = conn.cursor()
    try:
        cur.execute("SELECT cnpj_cpf FROM PessoaJuridica WHERE name = ?", (name,))
        row = cur.fetchone()
        if row and row[0]:
            return normalizar_doc(row[0])
    except Exception as e:
        print(f"[ERRO] Consulta por name falhou: {e}")
    return None

def primeiro_xml(pasta_xml: Path) -> Path | None:
    if not pasta_xml.exists():
        return None
    for xml in pasta_xml.rglob("*.xml"):
        try:
            if xml.is_file() and xml.stat().st_size > 0:
                return xml
        except Exception:
            continue
    return None

def detectar_namespace(root) -> dict:
    tag = root.tag
    if isinstance(tag, str) and tag.startswith("{"):
        uri = tag.split("}")[0].strip("{")
        return {"ns": uri}
    return {}

def cnpj_prestador(xml_path: Path) -> str:
    if etree is None or xml_path is None:
        return ""
    try:
        parser = etree.XMLParser(recover=True, encoding="utf-8")
        root = etree.parse(str(xml_path), parser=parser).getroot()
        ns = detectar_namespace(root) or NS
        xpaths = [
            "//ns:PrestadorServico/ns:IdentificacaoPrestador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:DeclaracaoPrestacaoServico/ns:InfDeclaracaoPrestacaoServico/ns:Prestador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:IdentificacaoPrestador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:Prestador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:InfNfse/ns:PrestadorServico/ns:IdentificacaoPrestador/ns:CpfCnpj/ns:Cnpj/text()",
        ]
        for xp in xpaths:
            vals = root.xpath(xp, namespaces=ns)
            if vals:
                return normalizar_doc(vals[0])
        vals = root.xpath("//ns:Cnpj/text()", namespaces=ns) if ns else root.xpath("//Cnpj/text()")
        if vals:
            return normalizar_doc(vals[0])
    except Exception as e:
        print(f"[ERRO] Falha ao extrair CNPJ do Prestador em '{xml_path}': {e}")
    return ""

def cnpj_tomador(xml_path: Path) -> str:
    if etree is None or xml_path is None:
        return ""
    try:
        parser = etree.XMLParser(recover=True, encoding="utf-8")
        root = etree.parse(str(xml_path), parser=parser).getroot()
        ns = detectar_namespace(root) or NS
        xpaths = [
            "//ns:Tomador/ns:IdentificacaoTomador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:DeclaracaoPrestacaoServico/ns:InfDeclaracaoPrestacaoServico/ns:Tomador/ns:IdentificacaoTomador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:IdentificacaoTomador/ns:CpfCnpj/ns:Cnpj/text()",
            "//ns:InfNfse/ns:Tomador/ns:IdentificacaoTomador/ns:CpfCnpj/ns:Cnpj/text()",
        ]
        for xp in xpaths:
            vals = root.xpath(xp, namespaces=ns)
            if vals:
                return normalizar_doc(vals[0])
        cnpjs = root.xpath("//ns:Cnpj/text()", namespaces=ns) if ns else root.xpath("//Cnpj/text()")
        cnpjs = [normalizar_doc(v) for v in cnpjs if v]
        cnpjs_unique = []
        for v in cnpjs:
            if v and v not in cnpjs_unique:
                cnpjs_unique.append(v)
        if len(cnpjs_unique) >= 2:
            return cnpjs_unique[1]
    except Exception as e:
        print(f"[ERRO] Falha ao extrair CNPJ do Tomador em '{xml_path}': {e}")
    return ""

# ====== EXTRAÇÃO DO CNPJ NO CABEÇALHO ======
def extrair_texto_pdf(pdf_path: Path) -> str:
    if pdf_extract_text is None:
        return ""
    try:
        return pdf_extract_text(str(pdf_path)) or ""
    except Exception as e:
        print(f"[WARN] Falha ao extrair texto de PDF '{pdf_path}': {e}")
        return ""

def extrair_texto_por_ocr_cabecalho(pdf_path: Path, dpi: int = 250) -> str:
    if pytesseract is None or convert_from_path is None:
        return ""
    try:
        pages = convert_from_path(str(pdf_path), dpi=dpi, first_page=1, last_page=1)
        if not pages:
            return ""
        img = pages[0]
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        top_crop = img.crop((0, 0, w, int(h * 0.25)))
        texto_top = pytesseract.image_to_string(top_crop, lang="por")
        if texto_top and "CNPJ" in texto_top.upper():
            return texto_top
        return pytesseract.image_to_string(img, lang="por")
    except Exception as e:
        print(f"[WARN] Falha no OCR de cabeçalho '{pdf_path}': {e}")
        return ""

def extrair_cnpj_cabecalho(pdf_path: Path) -> str:
    # 1) Texto embutido
    texto = extrair_texto_pdf(pdf_path)
    if texto:
        primeiras_linhas = "\n".join(texto.splitlines()[:30])
        m = HEADER_CNPJ_LINE_RE.search(primeiras_linhas)
        if m:
            return normalizar_doc(m.group(1))
    # 2) OCR do topo da 1ª página
    texto_ocr = extrair_texto_por_ocr_cabecalho(pdf_path)
    if texto_ocr:
        primeiras_linhas = "\n".join(texto_ocr.splitlines()[:40])
        m = HEADER_CNPJ_LINE_RE.search(primeiras_linhas)
        if m:
            return normalizar_doc(m.group(1))
        # Fallback: "CNPJ" seguido de número (variações)
        alt = re.search(r"CNPJ[^\d]{0,6}(" + CNPJ_PATTERN + ")", primeiras_linhas, re.IGNORECASE)
        if alt:
            return normalizar_doc(alt.group(1))
    return ""

# =========================
# REMOÇÃO DOS ITENS SUSPEITOS
# =========================
def remover_itens_suspeitos(base_mes: Path) -> list[str]:
    """
    Remove arquivos e pastas listados em ARQS_CANDIDATOS e PASTAS_CANDIDATAS
    dentro de base_mes / 'Relatórios'.
    Retorna lista de ações executadas (para log/relatório).
    """
    acoes = []
    relatorios_dir = base_mes / PASTA_RELATORIOS

    # Arquivos
    for nome_arq in ARQS_CANDIDATOS:
        alvo = relatorios_dir / nome_arq
        if alvo.exists():
            try:
                alvo.unlink()
                acoes.append(f"Arquivo removido: {alvo}")
            except Exception as e:
                acoes.append(f"[ERRO] Falha ao remover arquivo: {alvo} -> {e}")

    # Pastas (remover recursivamente)
    for nome_pasta in PASTAS_CANDIDATAS:
        alvo_dir = relatorios_dir / nome_pasta
        if alvo_dir.exists() and alvo_dir.is_dir():
            try:
                shutil.rmtree(alvo_dir)
                acoes.append(f"Pasta removida: {alvo_dir}")
            except Exception as e:
                acoes.append(f"[ERRO] Falha ao remover pasta: {alvo_dir} -> {e}")

    return acoes

# =========================
# RELATÓRIO
# =========================
def registrar_suspeito(registros: list[dict], empresa_nome: str, tipo_rel: str, caminho_pdf: Path, origem: str, doc_encontrado: str, doc_banco: str, observacao: str = "", acoes_remocao: list[str] | None = None):
    registros.append({
        "empresa": empresa_nome,
        "tipo": tipo_rel,
        "arquivo": str(caminho_pdf),
        "origem": origem,
        "doc_encontrado": doc_encontrado,
        "doc_banco": doc_banco,
        "observacao": observacao,
        "remocoes": acoes_remocao or [],
    })

def escrever_relatorio_txt(registros: list[dict], destino: Path):
    linhas = []
    header = f"Relatório de suspeitos e remoções - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    linhas.append(header)
    linhas.append("=" * len(header))
    for r in registros:
        linhas.append(f"- Empresa (name): {r['empresa']}")
        linhas.append(f"  Tipo: {r['tipo']}")
        linhas.append(f"  Arquivo analisado: {r['arquivo']}")
        linhas.append(f"  Origem da evidência: {r['origem']}")
        linhas.append(f"  Documento encontrado: {r['doc_encontrado']}")
        linhas.append(f"  Documento no banco:   {r['doc_banco']}")
        if r.get("observacao"):
            linhas.append(f"  Observação: {r['observacao']}")
        if r.get("remocoes"):
            linhas.append(f"  Remoções executadas:")
            for ac in r["remocoes"]:
                linhas.append(f"    - {ac}")
        linhas.append("")
    destino.write_text("\n".join(linhas), encoding="utf-8")
    print(f"[OK] Relatório TXT: {destino}")

def escrever_relatorio_csv(registros: list[dict], destino: Path):
    import csv
    campos = ["empresa", "tipo", "arquivo", "origem", "doc_encontrado", "doc_banco", "observacao", "remocoes"]
    with open(destino, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for r in registros:
            linha = dict(r)
            linha["remocoes"] = " | ".join(r.get("remocoes", []))
            w.writerow(linha)
    print(f"[OK] Relatório CSV: {destino}")

# =========================
# FLUXO PRINCIPAL
# =========================
def main(executar_remocao: bool = True):
    """
    executar_remocao=True: remove automaticamente os arquivos/pastas dos clientes marcados como suspeitos.
    Coloque False para apenas simular e gerar os relatórios.
    """
    conn = diagnostico_sqlite(SQLITE_DB)
    if conn is None:
        return

    if not BASE_CLIENTES.exists():
        print(f"[ERRO] Base não encontrada: {BASE_CLIENTES}")
        if conn:
            conn.close()
        return

    registros = []
    relatorio_txt = Path.cwd() / f"suspeitos_remocoes_mes{MES}.txt"
    relatorio_csv = Path.cwd() / f"suspeitos_remocoes_mes{MES}.csv"

    for empresa in BASE_CLIENTES.iterdir():
        if not empresa.is_dir():
            continue

        empresa_nome_exato = empresa.name
        base_mes = empresa / "FISCAL PJ" / ANO / MES

        relatorios_dir = base_mes / PASTA_RELATORIOS
        pasta_xml_prest = base_mes / PASTA_XML_PREST
        pasta_xml_tom = base_mes / PASTA_XML_TOM

        # Busca CNPJ/CPF do banco pelo name exato
        cnpj_ref = obter_cnpj_por_name(conn, empresa_nome_exato)
        if not cnpj_ref:
            print(f"[AVISO] CNPJ não encontrado para (name='{empresa_nome_exato}'). Pulando.")
            continue

        xml_prestados = primeiro_xml(pasta_xml_prest)
        xml_tomados = primeiro_xml(pasta_xml_tom)

        if relatorios_dir.exists():
            for arq in relatorios_dir.iterdir():
                if not arq.is_file():
                    continue
                stem = arq.stem

                # PRESTADOS
                if stem.startswith(TARGET_FILES["Prestados"]):
                    # XML
                    cnpj_xml = ""
                    if xml_prestados is not None:
                        cnpj_xml = cnpj_prestador(xml_prestados)
                        if cnpj_xml and cnpj_xml != cnpj_ref:
                            acoes = remover_itens_suspeitos(base_mes) if executar_remocao else []
                            registrar_suspeito(registros, empresa_nome_exato, "Prestados", arq, "XML", cnpj_xml, cnpj_ref, observacao=f"XML: {xml_prestados}", acoes_remocao=acoes)
                            continue  # já marcou como suspeito, segue próximo arquivo
                    # Cabeçalho do relatório
                    cnpj_header = extrair_cnpj_cabecalho(arq)
                    if cnpj_header and cnpj_header != cnpj_ref:
                        acoes = remover_itens_suspeitos(base_mes) if executar_remocao else []
                        registrar_suspeito(registros, empresa_nome_exato, "Prestados", arq, "OCR-Cabeçalho", cnpj_header, cnpj_ref, acoes_remocao=acoes)

                # TOMADOS
                elif stem.startswith(TARGET_FILES["Tomados"]):
                    cnpj_xml = ""
                    if xml_tomados is not None:
                        cnpj_xml = cnpj_tomador(xml_tomados)
                        if cnpj_xml and cnpj_xml != cnpj_ref:
                            acoes = remover_itens_suspeitos(base_mes) if executar_remocao else []
                            registrar_suspeito(registros, empresa_nome_exato, "Tomados", arq, "XML", cnpj_xml, cnpj_ref, observacao=f"XML: {xml_tomados}", acoes_remocao=acoes)
                            continue
                    cnpj_header = extrair_cnpj_cabecalho(arq)
                    if cnpj_header and cnpj_header != cnpj_ref:
                        acoes = remover_itens_suspeitos(base_mes) if executar_remocao else []
                        registrar_suspeito(registros, empresa_nome_exato, "Tomados", arq, "OCR-Cabeçalho", cnpj_header, cnpj_ref, acoes_remocao=acoes)

        else:
            print(f"[INFO] Pasta de Relatórios inexistente: {relatorios_dir}")

    # Relatórios finais
    escrever_relatorio_txt(registros, relatorio_txt)
    escrever_relatorio_csv(registros, relatorio_csv)
    print(f"[RESUMO] Total clientes/arquivos suspeitos: {len(registros)}")

    conn.close()

if __name__ == "__main__":
    # ATENÇÃO: Coloque executar_remocao=False para simular sem apagar nada.
    main(executar_remocao=False)