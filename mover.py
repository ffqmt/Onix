import re
import shutil
from pathlib import Path

# ===== CONFIGURE AQUI =====
ROOT_CLIENTES = Path(r"C:\Users\contaudi\OneDrive - CONTAUDI ASSESSORIA CONTABIL LTDA\Documentos - CONTAUDI ASSESSORIA CONTABIL LTDA\Contaudi - Onedrive\Clientes")
ANO = "2026"
MES = "01"
DRY_RUN = False  # True = só mostra/conta o que faria; False = executa de verdade
# ==========================

STATS = {
    "empresas_varridas": 0,
    "pastas_xml_encontradas": 0,

    "pastas_movidas": 0,          # quando move a pasta inteira (dst não existia)
    "pastas_merge": 0,            # quando dst já existia e foi feito merge
    "arquivos_movidos_no_merge": 0,

    "pastas_destino_existentes": 0,
    "pastas_destino_criadas": 0,

    "xmls_vistos_no_destino": 0,
    "xmls_sem_chave_44": 0,
    "xmls_ja_ok": 0,              # já estava com o nome final (ou igual após unique)
    "xmls_renomeados": 0,
    "xmls_colisao_nome": 0,       # quando precisou criar _1, _2...
}


def unique_path(path: Path) -> tuple[Path, bool]:
    """Retorna (path_final, teve_colisao)."""
    if not path.exists():
        return path, False
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate, True
        i += 1


def extract_nnf_from_access_key(filename: str) -> str | None:
    """
    Extrai nNF (9 dígitos) da chave NFe (44 dígitos) presente no nome do arquivo.
    Layout (padrão): cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3) nNF(9) tpEmis(1) cNF(8) DV(1)
    nNF = chave[25:34]
    """
    m = re.search(r"(\d{44})", filename)
    if not m:
        return None
    chave = m.group(1)
    nnf_9 = chave[25:34]
    return nnf_9.lstrip("0") or "0"


def move_merge(src_dir: Path, dst_dir: Path):
    """Move src_dir para dst_dir. Se dst_dir existir, move conteúdo (merge)."""
    if not src_dir.exists():
        return

    STATS["pastas_xml_encontradas"] += 1

    if not dst_dir.exists():
        STATS["pastas_destino_criadas"] += 1
        STATS["pastas_movidas"] += 1
        if DRY_RUN:
            print(f"[DRY] MOVE PASTA: '{src_dir}' -> '{dst_dir}'")
        else:
            shutil.move(str(src_dir), str(dst_dir))
        return

    STATS["pastas_destino_existentes"] += 1
    STATS["pastas_merge"] += 1
    if DRY_RUN:
        print(f"[DRY] MERGE: mover conteúdo de '{src_dir}' para '{dst_dir}'")
    else:
        dst_dir.mkdir(parents=True, exist_ok=True)

    for item in src_dir.iterdir():
        target = dst_dir / item.name
        if item.is_dir():
            move_merge(item, target)
        else:
            final_target, _ = unique_path(target)
            STATS["arquivos_movidos_no_merge"] += 1
            if DRY_RUN:
                print(f"[DRY] MOVE ARQ: '{item}' -> '{final_target}'")
            else:
                shutil.move(str(item), str(final_target))

    if not DRY_RUN:
        try:
            src_dir.rmdir()
        except OSError:
            pass


def rename_xmls_in_folder(folder: Path):
    if not folder.exists():
        return

    for f in folder.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() != ".xml":
            continue

        STATS["xmls_vistos_no_destino"] += 1

        nnf = extract_nnf_from_access_key(f.name)
        if not nnf:
            STATS["xmls_sem_chave_44"] += 1
            continue

        desired = f.with_name(f"{nnf}.xml")
        target, collided = unique_path(desired)
        if collided:
            STATS["xmls_colisao_nome"] += 1

        if target.name == f.name:
            STATS["xmls_ja_ok"] += 1
            continue

        STATS["xmls_renomeados"] += 1
        if DRY_RUN:
            print(f"[DRY] RENAME: '{f.name}' -> '{target.name}'")
        else:
            f.rename(target)


def main():
    if not ROOT_CLIENTES.exists():
        raise SystemExit(f"Raiz não encontrada: {ROOT_CLIENTES}")

    for empresa_dir in ROOT_CLIENTES.iterdir():
        if not empresa_dir.is_dir():
            continue

        STATS["empresas_varridas"] += 1

        base_mes = empresa_dir / "FISCAL PJ" / ANO / MES
        src = base_mes / "Relatórios" / "XML - Prestados"
        dst = base_mes / "XML - Prestados"

        if src.exists():
            move_merge(src, dst)

        if dst.exists():
            rename_xmls_in_folder(dst)

    print("\n===== RESUMO =====")
    print(f"Empresas varridas: {STATS['empresas_varridas']}")
    print(f"Pastas 'Relatórios\\XML - Tomados' encontradas: {STATS['pastas_xml_encontradas']}")
    print(f"Pastas movidas (inteiras): {STATS['pastas_movidas']}")
    print(f"Pastas com merge (destino já existia): {STATS['pastas_merge']}")
    print(f"Arquivos movidos durante merge: {STATS['arquivos_movidos_no_merge']}")
    print(f"Destinos já existentes: {STATS['pastas_destino_existentes']}")
    print(f"Destinos criados: {STATS['pastas_destino_criadas']}")
    print("---")
    print(f"XMLs vistos no destino: {STATS['xmls_vistos_no_destino']}")
    print(f"XMLs sem chave 44 dígitos no nome (não renomeados): {STATS['xmls_sem_chave_44']}")
    print(f"XMLs já estavam OK (sem renomear): {STATS['xmls_ja_ok']}")
    print(f"XMLs renomeados: {STATS['xmls_renomeados']}")
    print(f"Renomes com colisão (criou _1, _2...): {STATS['xmls_colisao_nome']}")


if __name__ == "__main__":
    main()
