import os
from datetime import datetime
import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple

# Namespace do seu XML de NFS-e (NFSe Nacional/SPED)
NS_SPED = "http://www.sped.fazenda.gov.br/nfse"
ET.register_namespace("", NS_SPED)  # faz sair xmlns="..." sem prefixo

# ===== Config do evento (ajuste conforme seu caso) =====
VERSAO_EVENTO = "1.01"
COD_EVENTO = "101101"  # cancelamento
VER_APLIC = "aplicacaov1.0"

AMB_GER = "1"          # conforme seu exemplo
TP_AMB = "1"           # 1=produção, 2=homologação
N_SEQ_EVENTO = "001"

CNPJ_AUTOR = "06310399000193"

C_MOTIVO = "2"
X_MOTIVO = "ERRO DE DIGITACAO NO PREENCHIMENTO DO DOCUMENTO"

# Se você não tiver nDFSe, deixe None (a tag não será escrita)
DEFAULT_N_DFSE = None  # exemplo: "0000000000070"


def qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def pretty_indent(elem: ET.Element, level: int = 0):
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            pretty_indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def find_target_folders(root_dir: str, target_folder_name: str = "XML- P. Canceladas") -> List[str]:
    """
    Retorna lista de caminhos de pastas cujo nome seja exatamente target_folder_name
    dentro de root_dir (busca recursiva).
    """
    matches: List[str] = []
    for cur_dir, subdirs, files in os.walk(root_dir):
        if os.path.basename(cur_dir) == target_folder_name:
            matches.append(cur_dir)
    return matches


def path_matches_year_month(folder_path: str, year: int, month: int) -> bool:
    """
    Filtra pela estrutura de pastas:
      ...\\<year>\\<MM>\\...\\XML- P. Canceladas

    Exemplo:
      ...\\2026\\01\\Relatórios\\XML- P. Canceladas
    """
    parts = [p for p in folder_path.split(os.sep) if p]
    year_s = str(year)
    month_s = f"{month:02d}"

    for i, p in enumerate(parts):
        if p == year_s and i + 1 < len(parts) and parts[i + 1] == month_s:
            return True
    return False


def extract_chave_from_filename(fname: str) -> Optional[str]:
    """
    Seu arquivo parece ser salvo como <CHAVE>.xml.
    Ex.: 51070401223109213000151000000000143826014147279513.xml
    """
    base = os.path.splitext(os.path.basename(fname))[0].strip()
    if base.isdigit() and len(base) >= 20:
        return base
    return None


def extract_chave_from_xml(root: ET.Element) -> Optional[str]:
    """
    Tenta obter a chave por:
      1) infNFSe/@Id  (ex.: NFS<chave>)
    """
    if root.tag != qn(NS_SPED, "NFSe"):
        return None

    inf = root.find(qn(NS_SPED, "infNFSe"))
    if inf is None:
        return None

    id_attr = (inf.get("Id") or "").strip()

    if id_attr.upper().startswith("NFS") and len(id_attr) > 3:
        possible = id_attr[3:]
        if possible.isdigit():
            return possible

    if id_attr.isdigit() and len(id_attr) >= 20:
        return id_attr

    return None


def _now_iso_local() -> str:
    # Ex.: 2026-02-03T10:50:12-04:00 (com fuso local)
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_evento_cancelamento_xml(
    ch_nfse: str,
    dh_evento: Optional[str] = None,
    dh_proc: Optional[str] = None,
    n_dfse: Optional[str] = DEFAULT_N_DFSE,
) -> ET.Element:
    """
    Gera o XML no layout:
      <evento xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">
        <infEvento Id="EVT{chave}{COD_EVENTO}">
          <verAplic>...</verAplic>
          <ambGer>...</ambGer>
          <nSeqEvento>...</nSeqEvento>
          <dhProc>...</dhProc>
          <nDFSe>...</nDFSe> (opcional)
          <pedRegEvento versao="1.01">
            <infPedReg Id="PRE{chave}{COD_EVENTO}">
              <tpAmb>...</tpAmb>
              <verAplic>...</verAplic>
              <dhEvento>...</dhEvento>
              <CNPJAutor>...</CNPJAutor>
              <chNFSe>...</chNFSe>
              <e101101>...</e101101>
            </infPedReg>
          </pedRegEvento>
        </infEvento>
      </evento>
    """
    if dh_evento is None:
        dh_evento = _now_iso_local()
    if dh_proc is None:
        dh_proc = _now_iso_local()

    id_evt = f"EVT{ch_nfse}{COD_EVENTO}"
    id_pre = f"PRE{ch_nfse}{COD_EVENTO}"

    evento = ET.Element(qn(NS_SPED, "evento"), {"versao": VERSAO_EVENTO})

    inf_evento = ET.SubElement(evento, qn(NS_SPED, "infEvento"), {"Id": id_evt})
    ET.SubElement(inf_evento, qn(NS_SPED, "verAplic")).text = VER_APLIC
    ET.SubElement(inf_evento, qn(NS_SPED, "ambGer")).text = AMB_GER
    ET.SubElement(inf_evento, qn(NS_SPED, "nSeqEvento")).text = N_SEQ_EVENTO
    ET.SubElement(inf_evento, qn(NS_SPED, "dhProc")).text = dh_proc

    if n_dfse:
        ET.SubElement(inf_evento, qn(NS_SPED, "nDFSe")).text = str(n_dfse)

    ped = ET.SubElement(inf_evento, qn(NS_SPED, "pedRegEvento"), {"versao": VERSAO_EVENTO})
    inf_ped = ET.SubElement(ped, qn(NS_SPED, "infPedReg"), {"Id": id_pre})

    ET.SubElement(inf_ped, qn(NS_SPED, "tpAmb")).text = TP_AMB
    ET.SubElement(inf_ped, qn(NS_SPED, "verAplic")).text = VER_APLIC
    ET.SubElement(inf_ped, qn(NS_SPED, "dhEvento")).text = dh_evento
    ET.SubElement(inf_ped, qn(NS_SPED, "CNPJAutor")).text = CNPJ_AUTOR
    ET.SubElement(inf_ped, qn(NS_SPED, "chNFSe")).text = ch_nfse

    det = ET.SubElement(inf_ped, qn(NS_SPED, f"e{COD_EVENTO}"))
    ET.SubElement(det, qn(NS_SPED, "xDesc")).text = "Cancelamento de NFS-e"
    ET.SubElement(det, qn(NS_SPED, "cMotivo")).text = C_MOTIVO
    ET.SubElement(det, qn(NS_SPED, "xMotivo")).text = X_MOTIVO

    return evento


def process_canceladas_folder_generate_events(
    input_dir: str,
    output_dir: str,
    default_data_hora: Optional[str] = None,
) -> Tuple[int, int, int]:
    """
    Lê XMLs de NFS-e na pasta input_dir e gera eventos de cancelamento em output_dir.
    Retorna (total_xml, gerados, ignorados).
    """
    os.makedirs(output_dir, exist_ok=True)

    total = 0
    gerados = 0
    ignorados = 0

    for fname in os.listdir(input_dir):
        if not fname.lower().endswith(".xml"):
            continue
        total += 1

        in_path = os.path.join(input_dir, fname)

        # 1) chave pelo nome do arquivo
        chave = extract_chave_from_filename(fname)

        # 2) fallback: chave pelo XML
        if not chave:
            try:
                tree = ET.parse(in_path)
                root_nfse = tree.getroot()
                chave = extract_chave_from_xml(root_nfse)
            except Exception:
                chave = None

        if not chave:
            ignorados += 1
            print(f"[{input_dir}] {fname}: ignorado (não consegui obter chNFSe)")
            continue

        # Se você passar default_data_hora, ela vira dhEvento e dhProc.
        evento_root = build_evento_cancelamento_xml(
            ch_nfse=chave,
            dh_evento=default_data_hora,
            dh_proc=default_data_hora,
            n_dfse=DEFAULT_N_DFSE,
        )
        pretty_indent(evento_root)

        out_name = f"EVT-CANC-{chave}.xml"
        out_path = os.path.join(output_dir, out_name)
        ET.ElementTree(evento_root).write(out_path, encoding="utf-8", xml_declaration=True)

        gerados += 1
        print(f"[{input_dir}] {fname}: evento gerado -> {out_name}")

    return total, gerados, ignorados


def process_root_for_cancel_folders_generate_events(
    root_dir: str,
    target_folder_name: str = "XML- P. Canceladas",
    event_subfolder_name: str = "EVENTO-CANCELAMENTO",
    only_year: int = 2026,
    only_month: int = 1,
    default_data_hora: Optional[str] = None,
):
    """
    Gera eventos APENAS para pastas que estejam sob ...\\<only_year>\\<only_month:02d>\\...

    Exemplo aceito:
      ...\\2026\\01\\Relatórios\\XML- P. Canceladas
    """
    targets_all = find_target_folders(root_dir, target_folder_name)
    targets = [p for p in targets_all if path_matches_year_month(p, only_year, only_month)]

    if not targets:
        print(f"Nenhuma pasta '{target_folder_name}' encontrada para {only_year}/{only_month:02d}.")
        return

    print(f"Pastas encontradas para {only_year}/{only_month:02d} ({len(targets)}):")
    for p in targets:
        print(f" - {p}")

    total_all = 0
    gerados_all = 0
    ignorados_all = 0

    for folder in targets:
        out_dir = os.path.join(folder, event_subfolder_name)
        print(f"\nGerando eventos na pasta: {out_dir}")
        total, gerados, ignorados = process_canceladas_folder_generate_events(
            input_dir=folder,
            output_dir=out_dir,
            default_data_hora=default_data_hora,
        )
        total_all += total
        gerados_all += gerados
        ignorados_all += ignorados

    print("\nResumo:")
    print(f" - XMLs lidos: {total_all}")
    print(f" - Eventos gerados: {gerados_all}")
    print(f" - Ignorados (sem chave): {ignorados_all}")


if __name__ == "__main__":
    raiz = r"F:\contaudi\OneDrive - CONTAUDI ASSESSORIA CONTABIL LTDA\Documentos - CONTAUDI ASSESSORIA CONTABIL LTDA\Contaudi - Onedrive\Clientes"

    # Somente notas do mês 01 de 2026 (pela estrutura de pastas ...\\2026\\01\\...)
    process_root_for_cancel_folders_generate_events(
        root_dir=raiz,
        target_folder_name="XML- P. Canceladas",
        event_subfolder_name="EVENTO-CANCELAMENTO",
        only_year=2026,
        only_month=6,
        default_data_hora=None,  # ou "2026-01-31T23:59:59-04:00"
    )
