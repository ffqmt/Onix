import shutil
import threading
from typing import List, Any

from selenium_stealth import stealth
from selenium import webdriver
from selenium.common import NoSuchElementException, ElementNotInteractableException, TimeoutException, \
 WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from time import sleep, time
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.support.wait import WebDriverWait
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
import glob
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

import os
import zipfile
import subprocess
import uuid

from OnixWeb.addons.OnixSender import SendRPAData
# from apps.authentication.models import Companies, ReportsRefreshControl, FilesParameters
# from apps.configs.globals import Globals
from OnixWeb.addons.appscontext import *

from OnixWeb.addons.models import PessoaJuridica, logData, ThreadingCounter, PessoaFisica, Empresas, AgendamentosRPA, \
    City, UF
from OnixWeb.addons.util import log_message, verify_downloaded, limpar_pasta

import base64
from PIL import Image
import cv2
from io import BytesIO
import easyocr
import re

import sys

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


root_path = os.path.abspath('')
USAR_LOGIN_MANUAL_SEFAZ = False
USAR_CERTIFICADO_SEFAZ = True

# --- CONFIGURAÇÕES DE ESTABILIZAÇÃO SEFAZ ---
AUTO_FALLBACK_LOGIN_MANUAL = True
SEFAZ_PAUSAR_CLOUDFLARED_DURANTE_RPA = False
SEFAZ_RESETAR_PROXY_PROCESSO = True
SEFAZ_DIAGNOSTICAR_REDE = True

_OCR_READER = None
_ocr_lock = threading.Lock()


def run_subprocess_seguro(cmd, timeout=10, shell=True, text=True):
 """
 Executa subprocess sem quebrar por UnicodeDecodeError no Windows.
 Use esta função sempre que precisar de subprocess.run com capture_output/text=True.
 """
 try:
  return subprocess.run(
   cmd,
   shell=shell,
   capture_output=True,
   text=text,
   encoding="utf-8",
   errors="replace",
   timeout=timeout
  )
 except UnicodeDecodeError as e:
  print(f"UnicodeDecodeError ignorado em subprocess: {e}")
  return None
 except Exception as e:
  print(f"Erro em subprocess: {e}")
  return None


def get_ocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        try:
            # Tenta inicializar com GPU
            _OCR_READER = easyocr.Reader(['pt'], gpu=True)
        except Exception:
            try:
                # Fallback para CPU
                _OCR_READER = easyocr.Reader(['pt'], gpu=False)
            except Exception as e:
                print(f"Erro ao inicializar EasyOCR: {e}")
    return _OCR_READER



def pasta_tem_arquivos_validos(caminho_pasta) -> bool:
    if not os.path.exists(caminho_pasta):
        return False
    for r, dirs, files in os.walk(caminho_pasta):
        for file in files:
            lower_file = file.lower()
            if lower_file.endswith('.crdownload') or lower_file.endswith('.tmp'):
                continue
            if file.startswith('~') or file.startswith('.'):
                continue
            return True
    return False


def pagina_tem_erro_conexao(driver) -> bool:
    try:
        title = (driver.title or "").strip()
        current_url = driver.current_url or ""
        if current_url.startswith("chrome-error://"):
            return True
        
        # Procura conteúdo de erro na tag body
        body_element = driver.find_elements(By.TAG_NAME, 'body')
        body_text = ""
        if body_element:
            body_text = (body_element[0].text or "").strip()
            
        error_indicators = [
            "ERR_CONNECTION_RESET",
            "ERR_TIMED_OUT",
            "ERR_CONNECTION_CLOSED",
            "ERR_CONNECTION_REFUSED",
            "DNS_PROBE_FINISHED",
            "This site can't be reached",
            "Não é possível acessar esse site",
            "não pode ser acessado",
            "Connection was reset"
        ]
        for indicator in error_indicators:
            if indicator.lower() in title.lower() or indicator.lower() in body_text.lower():
                return True
        return False
    except Exception:
        return True


def diagnosticar_estado_pagina(driver, nome_thread, contexto) -> None:
    try:
        debug_dir = r"C:\Onix\Onix\debug_sefaz"
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Salva o código HTML
        html_path = os.path.join(debug_dir, f"pagina_{contexto}_{timestamp}_{nome_thread}.html")
        try:
            html_content = driver.page_source
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except Exception as e:
            print(f"Erro ao salvar HTML da pagina: {e}")
            
        # Salva screenshot
        img_path = os.path.join(debug_dir, f"pagina_{contexto}_{timestamp}_{nome_thread}.png")
        try:
            driver.save_screenshot(img_path)
        except Exception as e:
            print(f"Erro ao salvar screenshot da pagina: {e}")
            
        # Loga no OnixWeb se disponível
        try:
            includeLogData(
                nome_thread,
                f"DIAGNOSTICO PAGINA - {contexto}",
                f"URL atual: {driver.current_url or 'N/A'}. Title: {driver.title or 'N/A'}. Arquivos salvos em debug_sefaz.",
                "BOT",
                "SEFAZ",
                "danger-gradient",
                "ERRO",
                "danger-gradient"
            )
        except Exception:
            pass
    except Exception as e:
        print(f"Erro no diagnostico da pagina: {e}")


def abrir_url_sefaz(driver, url, nome_thread='BOT', tentativas=5, timeout=45) -> bool:
    print(f"Abrindo URL SEFAZ: {url} (tentativa/timeout: {tentativas}/{timeout})")
    import random
    for tent in range(1, tentativas + 1):
        try:
            driver.set_page_load_timeout(timeout)
            driver.get(url)
            wait = random.uniform(4.0, 7.0)
            print(f"  Esperando {wait:.1f}s para F5 JS challenge assentar...")
            sleep(wait)
            
            # Verifica erros de conexão do Chrome
            if pagina_tem_erro_conexao(driver):
                backoff = min(15 * tent, 60) + random.uniform(5, 15)
                print(f"Erro de conexao detectado na tentativa {tent} para a URL: {url}. Backoff de {backoff:.0f}s...")
                diagnosticar_estado_pagina(driver, nome_thread, f"erro_conexao_tentativa_{tent}")
                if tent < tentativas:
                    sleep(backoff)
                    continue
                return False
            
            # Página carregada com sucesso
            return True
        except TimeoutException:
            backoff = min(20 * tent, 90) + random.uniform(5, 15)
            print(f"TimeoutException ao carregar a página na tentativa {tent}. Backoff de {backoff:.0f}s...")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            diagnosticar_estado_pagina(driver, nome_thread, f"timeout_tentativa_{tent}")
            if tent < tentativas:
                sleep(backoff)
                continue
        except WebDriverException as we:
            backoff = min(20 * tent, 90) + random.uniform(5, 15)
            print(f"WebDriverException ao carregar a página na tentativa {tent}: {str(we)[:80]}. Backoff de {backoff:.0f}s...")
            diagnosticar_estado_pagina(driver, nome_thread, f"webdriver_erro_tentativa_{tent}")
            if tent < tentativas:
                sleep(backoff)
                continue
        except Exception as e:
            print(f"Erro desconhecido ao carregar a página na tentativa {tent}: {e}")
            if tent < tentativas:
                sleep(5.0)
                continue
    return False


def resolver_captcha_base64(base64_link, nome_thread=None) -> str | None:
    try:
        if base64_link.startswith('data:image/png;base64,'):
            base64_link = base64_link.replace('data:image/png;base64,', '')
        missing_padding = len(base64_link) % 4
        if missing_padding:
            base64_link += '=' * (4 - missing_padding)
        image_data = base64.b64decode(base64_link)
        
        debug_dir = r"C:\Onix\Onix\debug_sefaz"
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Salva original em debug
        orig_name = f"captcha_orig_{timestamp}_{nome_thread or 'BOT'}.png"
        orig_path = os.path.join(debug_dir, orig_name)
        with open(orig_path, "wb") as f:
            f.write(image_data)
            
        # Converte para OpenCV
        image = Image.open(BytesIO(image_data))
        temp_name = f"captcha_temp_{nome_thread or 'BOT'}.png"
        temp_path = os.path.join(debug_dir, temp_name)
        image.save(temp_path, 'PNG')
        
        img = cv2.imread(temp_path)
        if img is None:
            return None
            
        img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Variantes para OCR
        img_v1 = cv2.medianBlur(img_gray, 3)
        img_v2 = cv2.resize(img_gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        img_v2 = cv2.adaptiveThreshold(img_v2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        _, img_v3 = cv2.threshold(img_gray, 127, 255, cv2.THRESH_BINARY)
        
        variantes = [
            ("v1_median", img_v1),
            ("v2_adaptive", img_v2),
            ("v3_threshold", img_v3)
        ]
        
        reader = get_ocr_reader()
        if not reader:
            print("EasyOCR Reader nao carregado.")
            return None
            
        for var_name, var_img in variantes:
            var_path = os.path.join(debug_dir, f"captcha_{var_name}_{nome_thread or 'BOT'}.png")
            cv2.imwrite(var_path, var_img)
            
            with _ocr_lock:
                resultado = reader.readtext(var_path)
                
            if resultado:
                text = "".join([res[1] for res in resultado])
                recaptcha = re.sub(r'[^a-zA-Z0-9]', '', text.lower().strip())
                if len(recaptcha) == 4:
                    success_name = f"captcha_success_{timestamp}_{nome_thread or 'BOT'}.png"
                    cv2.imwrite(os.path.join(debug_dir, success_name), var_img)
                    return recaptcha
        return None
    except Exception as e:
        print(f"Erro ao resolver_captcha_base64: {e}")
        return None


def diagnosticar_rede_sefaz(nome_thread=None) -> dict:
 debug_dir = r"C:\Onix\Onix\debug_sefaz"
 os.makedirs(debug_dir, exist_ok=True)
 timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
 out_file = os.path.join(debug_dir, f"rede_{timestamp}.txt")

 def run_cmd(title, cmd):
  try:
   res = run_subprocess_seguro(
    cmd,
    shell=True,
    text=True,
    timeout=10
   )

   if res is None:
    return f"=== {title} ===\nErro: subprocess retornou None\n\n"

   stdout = res.stdout or ""
   stderr = res.stderr or ""

   return (
    f"=== {title} ===\n"
    f"RETURN CODE: {res.returncode}\n"
    f"STDOUT:\n{stdout}\n"
    f"STDERR:\n{stderr}\n\n"
   )
  except Exception as e:
   return f"=== {title} ===\nErro: {e}\n\n"

 content = f"DIAGNOSTICO DE REDE SEFAZ - {datetime.now()}\n"
 content += f"Thread: {nome_thread or 'BOT'}\n\n"

 content += run_cmd(
  "Servicos Cloudflare",
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-Service | Where-Object {$_.Name -like '*cloud*' -or $_.DisplayName -like '*Cloudflare*'}\""
 )
 content += run_cmd(
  "Processos Cloudflared/WARP",
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-Process -Name cloudflared, warp-svc, warp-cli -ErrorAction SilentlyContinue\""
 )
 content += run_cmd(
  "Proxy WinHTTP",
  "netsh winhttp show proxy"
 )

 content += "=== Variaveis de Ambiente Proxy ===\n"
 for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]:
  content += f"{var}: {os.environ.get(var, 'Nao definida')}\n"
 content += "\n"

 content += run_cmd(
  "DNS IPv4",
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-DnsClientServerAddress -AddressFamily IPv4\""
 )
 content += run_cmd(
  "Adaptadores de Rede",
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-NetAdapter\""
 )
 content += run_cmd(
  "Rotas de IP",
  "route print"
 )
 content += run_cmd(
  "TCP Test 443 SEFAZ",
  "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Test-NetConnection www.sefaz.mt.gov.br -Port 443\""
 )
 content += run_cmd(
  "Curl SEFAZ HEAD",
  "curl.exe -I -v https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml"
 )

 try:
  with open(out_file, "w", encoding="utf-8", errors="replace") as f:
   f.write(content)
  print(f"Diagnóstico de rede salvo em {out_file}")
 except Exception as e:
  print(f"Erro ao salvar arquivo de diagnostico de rede: {e}")

 return {"status": "ok", "path": out_file}


def preparar_rede_para_sefaz(nome_thread=None) -> dict:
 estado = {
  "cloudflared_was_running": False,
  "original_env": {}
 }

 print("Preparando rede para SEFAZ-MT...")

 # 1. Registrar variáveis de proxy no processo e limpar
 for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]:
  if var in os.environ:
   estado["original_env"][var] = os.environ[var]
   if SEFAZ_RESETAR_PROXY_PROCESSO:
    del os.environ[var]
    print(f"Variavel de processo {var} limpa.")

 # 2. Resetar WinHTTP proxy
 if SEFAZ_RESETAR_PROXY_PROCESSO:
  try:
   res = run_subprocess_seguro(
    "netsh winhttp reset proxy",
    shell=True,
    text=True,
    timeout=10
   )
   if res:
    print("WinHTTP Proxy resetado para direto.")
    if res.stderr:
     print(f"WinHTTP stderr: {res.stderr}")
   else:
    print("WinHTTP Proxy resetado/ignorado sem retorno.")
  except Exception as e:
   print(f"Erro ao resetar proxy WinHTTP: {e}")

 # 3. Diagnóstico antes
 if SEFAZ_DIAGNOSTICAR_REDE:
  try:
   diagnosticar_rede_sefaz(nome_thread)
  except Exception as e:
   print(f"Erro ao diagnosticar rede: {e}")

 # 4. Pausar cloudflared se configurado
 if SEFAZ_PAUSAR_CLOUDFLARED_DURANTE_RPA:
  try:
   chk = run_subprocess_seguro(
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \"(Get-Service -Name cloudflared -ErrorAction SilentlyContinue).Status\"",
    shell=True,
    text=True,
    timeout=10
   )

   if chk and "Running" in (chk.stdout or ""):
    estado["cloudflared_was_running"] = True
    print("Serviço cloudflared esta rodando. Tentando parar...")

    stop_res = run_subprocess_seguro(
     "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Stop-Service -Name cloudflared -ErrorAction SilentlyContinue\"",
     shell=True,
     text=True,
     timeout=15
    )

    if stop_res:
     print(f"Stop-Service stdout: {stop_res.stdout} stderr: {stop_res.stderr}")

  except Exception as e:
   print(f"Erro ao verificar/parar servico cloudflared: {e}")

  try:
   chk_proc = run_subprocess_seguro(
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Get-Process -Name cloudflared -ErrorAction SilentlyContinue\"",
    shell=True,
    text=True,
    timeout=10
   )

   if chk_proc and (chk_proc.stdout or "").strip():
    print("Processo cloudflared.exe em execucao. Matando processo...")
    run_subprocess_seguro(
     "taskkill /f /im cloudflared.exe",
     shell=True,
     text=True,
     timeout=10
    )
    estado["cloudflared_was_running"] = True

  except Exception as e:
   print(f"Erro ao matar processo cloudflared.exe: {e}")

 return estado


def restaurar_rede_pos_sefaz(estado_anterior, nome_thread=None) -> None:
 print("Restaurando rede pos SEFAZ-MT...")
 if not estado_anterior:
  return

 # 1. Restaurar proxy no processo
 original_env = estado_anterior.get("original_env", {})
 for var, val in original_env.items():
  os.environ[var] = val
  print(f"Variavel de processo {var} restaurada.")

 # 2. Restaurar cloudflared se estava rodando
 if SEFAZ_PAUSAR_CLOUDFLARED_DURANTE_RPA and estado_anterior.get("cloudflared_was_running"):
  try:
   print("Religando servico cloudflared...")

   start_res = run_subprocess_seguro(
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \"Start-Service -Name cloudflared -ErrorAction SilentlyContinue\"",
    shell=True,
    text=True,
    timeout=15
   )

   if start_res:
    print(f"Start-Service stdout: {start_res.stdout} stderr: {start_res.stderr}")

  except Exception as e:
   print(f"Erro ao religar servico cloudflared: {e}")


def includeLogData(threadName, log_title, log_desc, cnpj_cpf, tipo, bg_tipo, status, bg_status):
    with app.app_context():
        data = logData()
        data.thread_name = threadName
        data.log_title = log_title
        data.log_desc = log_desc
        data.cnpj_cpf = cnpj_cpf
        data.data = datetime.now()
        data.tipo = tipo
        data.bg_tipo = bg_tipo
        data.status = status
        data.bg_status = bg_status
        db.session.add(data)
        db.session.commit()


def setPercentilProcesso(threadName, percentil):
    with app.app_context():
        threadToUpdate = ThreadingCounter.query.filter_by(thread_name=threadName).first()
        threadToUpdate.percentil = percentil
        db.session.commit()


def checkParamPadrao(TipoPessoa, idPessoa):
    with app.app_context():
        if TipoPessoa == 'PJ':
            Pessoa = PessoaJuridica.query.filter_by(id=idPessoa).first()
        elif TipoPessoa == 'PF':
            Pessoa = PessoaFisica.query.filter_by(id=idPessoa).first()

    return {
        'nfe_saida': bool(Pessoa.sefaz_nfe_saida),
        'nfe_entrada': bool(Pessoa.sefaz_nfe_entrada),
        'cte_emissor': bool(Pessoa.sefaz_cte_emitido),
        'cte_tomador': bool(Pessoa.sefaz_cte_tomado),
        'nfce_emitida': bool(Pessoa.sefaz_nfce),
    }


def exec_LOGIN_MANUAL(driver, nome_thread, timeout=300):
 """
 Abre a tela de login da SEFAZ e aguarda o usuário autenticar manualmente.
 Útil para evitar captcha/OCR/bloqueio em Selenium.
 """
 includeLogData(
  nome_thread,
  'LOGIN MANUAL - SEFAZ',
  'Aguardando login manual na SEFAZ. Faça o login no navegador aberto.',
  'BOT',
  'SEFAZ',
  'warning-gradient',
  'ATENÇÃO',
  'warning-gradient'
 )

 login_url = 'https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml'

 try:
  abrir_url_sefaz(driver, login_url, nome_thread)
 except Exception:
  pass

 inicio = time()

 while time() - inicio < timeout:
  try:
   current_url = driver.current_url or ''

   # Critério 1: URL da página inicial logada
   if 'paginainicial.xhtml' in current_url:
    includeLogData(
     nome_thread,
     'LOGIN MANUAL - SEFAZ',
     'Login manual detectado com sucesso.',
     'BOT',
     'SEFAZ',
     'warning-gradient',
     'SUCESSO',
     'success-gradient'
    )
    return True

   # Critério 2: algum elemento conhecido pós-login
   try:
    body_text = driver.find_element(By.TAG_NAME, 'body').text or ''
    if 'Sair' in body_text or 'Página Inicial' in body_text or 'Bem-vindo' in body_text:
     includeLogData(
      nome_thread,
      'LOGIN MANUAL - SEFAZ',
      'Login manual detectado por conteúdo da página.',
      'BOT',
      'SEFAZ',
      'warning-gradient',
      'SUCESSO',
      'success-gradient'
     )
     return True
   except Exception:
    pass

  except WebDriverException:
   raise

  sleep(2)

 includeLogData(
  nome_thread,
  'LOGIN MANUAL - SEFAZ',
  f'Timeout aguardando login manual após {timeout} segundos.',
  'BOT',
  'SEFAZ',
  'danger-gradient',
  'ERRO',
  'danger-gradient'
 )

 return False


def dadosLoginSefaz(EmpresaExec):
    with app.app_context():
        Empresa = Empresas.query.filter_by(id=EmpresaExec).first()

    return {'login': Empresa.login_contabilista, 'senha': Empresa.senha_contabilista}


def MainExecution_Juridica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
 from selenium.common.exceptions import WebDriverException

 thread_atual = threading.current_thread()
 nome_thread = thread_atual.name
 caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
 dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
 dadosLogin = dadosLoginSefaz(EmpresaExec)
 listaLen = len(listaPessoas)
 percentilProcesso = 80
 percentilPorPessoa = int(percentilProcesso / listaLen) if listaLen else 0
 percentilInicial = 5
 setPercentilProcesso(nome_thread, percentilInicial)

 estado_rede = {}
 driver = None
 try:
  estado_rede = preparar_rede_para_sefaz(nome_thread)
  
  # ########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########
  driver = IniciarDriver(nome_thread=nome_thread)
  
  # ########## REALIZA O LOGIN UNICO SEFAZ ###########
  if USAR_LOGIN_MANUAL_SEFAZ:
   logado = exec_LOGIN_MANUAL(driver, nome_thread, timeout=300)
  else:
   logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

  if logado:
   for pessoa in dados:
    tipo_exec = 'PJ'

    includeLogData(
     nome_thread,
     f'PROCESSOS - {pessoa["name"]}',
     'Iniciando processos para a empresa...',
     'BOT',
     'BOT',
     'primary-gradient',
     'SUCESSO',
     'success-gradient'
    )

    # RETRY POR PESSOA (se o Chrome/Driver cair, recria + reloga e repete a mesma pessoa)
    max_tentativas_pessoa = 2
    for tentativa in range(1, max_tentativas_pessoa + 1):
     try:
      name_company = pessoa['name']
      id_company = pessoa['id']
      username = pessoa['username']
      ie = pessoa['ie']

      # ########### DADOS DE ANO E MES DA EXECUÇÃO ###########
      anoExec = f'{Ano}'
      mesExec = f'0{Mes}' if len(str(Mes)) == 1 else f'{Mes}'

      # ########## VERIFICA PASTA TEMPORARIA ##########
      nome_empresa = f"{name_company}"
      pastaArquivos = os.path.join(
       caminho_pasta, nome_empresa, "FISCAL PJ", anoExec, mesExec, "Relatórios"
      )
      os.makedirs(pastaArquivos, exist_ok=True)

      driver.execute_cdp_cmd(
       'Page.setDownloadBehavior',
       {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'}
      )

      # ######### EXECUTA ESCOLHAS APOS LOGADO ########
      if listaParametros['nfe_saida']:
       exec_NFE_SAIDA(
        driver=driver,
        nome_thread=nome_thread,
        tipo_exec=tipo_exec,
        name_company=name_company,
        cnpj_cpf=username,
        idDoc=username,
        execMes=mesExec,
        execAno=anoExec,
        pastaArquivos=pastaArquivos
       )
      if listaParametros['nfe_entrada']:
       exec_NFE_ENTRADA(
        driver=driver,
        nome_thread=nome_thread,
        tipo_exec=tipo_exec,
        name_company=name_company,
        cnpj_cpf=username,
        idDoc=username,
        execMes=mesExec,
        execAno=anoExec,
        pastaArquivos=pastaArquivos
       )

      if listaParametros['cte_emissor']:
       exec_CTE_EMISSOR(
        driver=driver,
        nome_thread=nome_thread,
        tipo_exec=tipo_exec,
        name_company=name_company,
        cnpj_cpf=username,
        idDoc=username,
        execMes=mesExec,
        execAno=anoExec,
        pastaArquivos=pastaArquivos
       )

      if listaParametros['cte_tomador']:
       exec_CTE_TOMADOR(
        driver=driver,
        nome_thread=nome_thread,
        tipo_exec=tipo_exec,
        name_company=name_company,
        cnpj_cpf=username,
        idDoc=username,
        execMes=mesExec,
        execAno=anoExec,
        pastaArquivos=pastaArquivos
       )

      if listaParametros['nfce_emitida']:
       exec_NFCE(
        driver=driver,
        nome_thread=nome_thread,
        name_company=name_company,
        cnpj_cpf=username,
        ie=ie,
        execMes=mesExec,
        execAno=anoExec,
        pastaArquivos=pastaArquivos
       )

      sleep(1)
      limpar_pasta(pastaArquivos)

      print(f'Processo Finalizado para: ({id_company}) {name_company}')
      includeLogData(
       nome_thread,
       f'PROCESSOS - {pessoa["name"]}',
       'Processos finalizados para a pessoa...',
       'BOT',
       'BOT',
       'primary-gradient',
       'SUCESSO',
       'success-gradient'
      )
      setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
      percentilInicial = percentilInicial + percentilPorPessoa

      # sucesso -> sai do retry desta pessoa
      break

     except WebDriverException as e:
      includeLogData(
       nome_thread,
       f'DRIVER CAIU - {pessoa["name"]}',
       f'Chrome/Driver caiu (tentativa {tentativa}/{max_tentativas_pessoa}). Recriando driver e relogando...',
       f'{pessoa.get("username", "BOT")}',
       'RPA',
       'danger-gradient',
       'ERRO',
       'danger-gradient'
      )

      # encerra driver antigo (se ainda existir)
      try:
       driver.quit()
      except Exception:
       pass

      if tentativa < max_tentativas_pessoa:
       driver = IniciarDriver(nome_thread=nome_thread)
       logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])
       if not logado:
        raise
       continue

      # estourou tentativas -> propaga erro
      raise

  # ########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######
  try:
   if pasta_tem_arquivos_validos(caminho_pasta):
    shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
    includeLogData(
     nome_thread,
     f'ARQUIVO FINAL',
     'Arquivo gerado e disponível!',
     'BOT',
     'BOT',
     'primary-gradient',
     'SUCESSO',
     'success-gradient'
    )
   else:
    includeLogData(
     nome_thread,
     f'ARQUIVO FINAL',
     'Nenhum arquivo gerado. ZIP não será criado.',
     'BOT',
     'BOT',
     'warning-gradient',
     'ATENÇÃO',
     'warning-gradient'
    )
   setPercentilProcesso(nome_thread, 100)
  except Exception:
   includeLogData(
    nome_thread,
    f'ARQUIVO FINAL',
    'Erro ao gerar arquivo!',
    'BOT',
    'RPA',
    'primary-gradient',
    'ERRO',
    'danger'
   )

 finally:
  sleep(3)
  if driver:
   try:
    driver.quit()
   except Exception:
    pass
  try:
   restaurar_rede_pos_sefaz(estado_rede, nome_thread)
  except Exception as e:
   print(f"Erro ao restaurar rede: {e}")


def MainExecution_Juridica_Padrao(listaPessoas, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen) if listaLen else 0
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    estado_rede = {}
    driver = None
    try:
        estado_rede = preparar_rede_para_sefaz(nome_thread)
        '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
        driver = IniciarDriver(nome_thread=nome_thread)
        '########## REALIZA O LOGIN UNICO SEFAZ ###########'
        logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

        if logado:
            for pessoa in dados:
                includeLogData(nome_thread,
                               f'PROCESSOS - {pessoa["name"]}',
                               'Iniciando processos para a empresa...',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')

                name_company = pessoa['name']
                id_company = pessoa['id']
                username = pessoa['username']
                ie = pessoa['ie']
                tipo_exec = 'PJ'
                listaParametros = checkParamPadrao(tipo_exec, id_company)

                '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
                anoExec = f'{Ano}'
                if len(str(Mes)) == 1:
                    mesExec = f'0{Mes}'
                else:
                    mesExec = f'{Mes}'

                '########## VERIFICA PASTA TEMPORARIA ##########'
                nome_empresa = f"{name_company}"
                pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "FISCAL PJ", anoExec, mesExec, "Relatórios")
                if not os.path.exists(pastaArquivos):
                    os.makedirs(pastaArquivos)

                driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                       {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

                '######### EXECUTA ESCOLHAS APOS LOGADO ########'
                if listaParametros['nfe_saida']:
                    exec_NFE_SAIDA(driver=driver,
                                   nome_thread=nome_thread,
                                   tipo_exec=tipo_exec,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['nfe_entrada']:
                    exec_NFE_ENTRADA(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=username,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['cte_emissor']:
                    exec_CTE_EMISSOR(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=username,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['cte_tomador']:
                    exec_CTE_TOMADOR(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=username,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['nfce_emitida']:
                    exec_NFCE(driver=driver,
                              nome_thread=nome_thread,
                              name_company=name_company,
                              cnpj_cpf=username,
                              ie=ie,
                              execMes=mesExec,
                              execAno=anoExec,
                              pastaArquivos=pastaArquivos)
                sleep(1)
                limpar_pasta(pastaArquivos)

                print(f'Processo Finalizado para: ({id_company}) {name_company}')
                includeLogData(nome_thread,
                               f'PROCESSOS - {pessoa["name"]}',
                               'Processos finalizados para a pessoa...',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
                setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
                percentilInicial = percentilInicial + percentilPorPessoa

        '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
        try:
            if pasta_tem_arquivos_validos(caminho_pasta):
                shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
                includeLogData(nome_thread,
                               f'ARQUIVO FINAL',
                               'Arquivo gerado e disponível!',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
            else:
                includeLogData(nome_thread,
                               f'ARQUIVO FINAL',
                               'Nenhum arquivo gerado. ZIP não será criado.',
                               'BOT',
                               'BOT',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
            setPercentilProcesso(nome_thread, 100)
        except Exception as e:
            includeLogData(nome_thread,
                           f'ARQUIVO FINAL',
                           'Erro ao gerar arquivo!',
                           'BOT',
                           'RPA',
                           'primary-gradient',
                           'ERRO',
                           'danger')

    finally:
        '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
        sleep(3)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        try:
            restaurar_rede_pos_sefaz(estado_rede, nome_thread)
        except Exception as e:
            print(f"Erro ao restaurar rede: {e}")


def MainExecution_Fisica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPF(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen) if listaLen else 0
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    estado_rede = {}
    driver = None
    try:
        estado_rede = preparar_rede_para_sefaz(nome_thread)
        '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
        driver = IniciarDriver(nome_thread=nome_thread)
        '########## REALIZA O LOGIN UNICO SEFAZ ###########'
        if USAR_LOGIN_MANUAL_SEFAZ:
            logado = exec_LOGIN_MANUAL(driver, nome_thread, timeout=300)
        else:
            logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

        if logado:
            for pessoa in dados:
                tipo_exec = 'PF'
                includeLogData(nome_thread,
                               f'PROCESSOS - {pessoa["name"]}',
                               'Iniciando processos para a pessoa...',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')

                name_company = pessoa['name']
                id_company = pessoa['id']
                username = pessoa['username']
                ie = pessoa['ie']

                '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
                anoExec = f'{Ano}'
                if len(str(Mes)) == 1:
                    mesExec = f'0{Mes}'
                else:
                    mesExec = f'{Mes}'

                '########## VERIFICA PASTA TEMPORARIA ##########'
                nome_empresa = f"{name_company}"
                pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "RURAL", anoExec, mesExec,
                                             "Relatórios")
                if not os.path.exists(pastaArquivos):
                    os.makedirs(pastaArquivos)

                driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                       {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

                '######### EXECUTA ESCOLHAS APOS LOGADO ########'
                if listaParametros['nfe_saida']:
                    exec_NFE_SAIDA(driver=driver,
                                   nome_thread=nome_thread,
                                   tipo_exec=tipo_exec,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=ie,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['nfe_entrada']:
                    exec_NFE_ENTRADA(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=ie,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['cte_emissor']:
                    exec_CTE_EMISSOR(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=ie,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['cte_tomador']:
                    exec_CTE_TOMADOR(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=username,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['nfce_emitida']:
                    exec_NFCE(driver=driver,
                              nome_thread=nome_thread,
                              name_company=name_company,
                              cnpj_cpf=username,
                              ie=ie,
                              execMes=mesExec,
                              execAno=anoExec,
                              pastaArquivos=pastaArquivos)

                sleep(1)
                limpar_pasta(pastaArquivos)

                print(f'Processo Finalizado para: ({id_company}) {name_company}')
                includeLogData(nome_thread,
                               f'PROCESSOS - {pessoa["name"]}',
                               'Processos finalizados para a pessoa...',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
                setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
                percentilInicial = percentilInicial + percentilPorPessoa

        '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
        try:
            if pasta_tem_arquivos_validos(caminho_pasta):
                shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
                includeLogData(nome_thread,
                               f'ARQUIVO FINAL',
                               'Arquivo gerado e disponível!',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
            else:
                includeLogData(nome_thread,
                               f'ARQUIVO FINAL',
                               'Nenhum arquivo gerado. ZIP não será criado.',
                               'BOT',
                               'BOT',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
            setPercentilProcesso(nome_thread, 100)
        except Exception as e:
            includeLogData(nome_thread,
                           f'ARQUIVO FINAL',
                           'Erro ao gerar arquivo!',
                           'BOT',
                           'RPA',
                           'primary-gradient',
                           'ERRO',
                           'danger')

    finally:
        '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
        sleep(3)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        try:
            restaurar_rede_pos_sefaz(estado_rede, nome_thread)
        except Exception as e:
            print(f"Erro ao restaurar rede: {e}")


def MainExecution_Fisica_Padrao(listaPessoas, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPF(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen) if listaLen else 0
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    estado_rede = {}
    driver = None
    try:
        estado_rede = preparar_rede_para_sefaz(nome_thread)
        '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
        driver = IniciarDriver(nome_thread=nome_thread)
        '########## REALIZA O LOGIN UNICO SEFAZ ###########'
        logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

        if logado:
            for pessoa in dados:
                includeLogData(nome_thread,
                               f'PROCESSOS - {pessoa["name"]}',
                               'Iniciando processos para a pessoa...',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')

                name_company = pessoa['name']
                id_company = pessoa['id']
                username = pessoa['username']
                ie = pessoa['ie']
                tipo_exec = 'PF'
                listaParametros = checkParamPadrao(tipo_exec, id_company)

                '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
                anoExec = f'{Ano}'
                if len(str(Mes)) == 1:
                    mesExec = f'0{Mes}'
                else:
                    mesExec = f'{Mes}'

                '########## VERIFICA PASTA TEMPORARIA ##########'
                nome_empresa = f"{name_company}"
                pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "RURAL", anoExec, mesExec,
                                             "Relatórios")
                if not os.path.exists(pastaArquivos):
                    os.makedirs(pastaArquivos)

                driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                       {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

                '######### EXECUTA ESCOLHAS APOS LOGADO ########'
                if listaParametros['nfe_saida']:
                    exec_NFE_SAIDA(driver=driver,
                                   nome_thread=nome_thread,
                                   tipo_exec=tipo_exec,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=ie,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['nfe_entrada']:
                    exec_NFE_ENTRADA(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=ie,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['cte_emissor']:
                    exec_CTE_EMISSOR(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=ie,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['cte_tomador']:
                    exec_CTE_TOMADOR(driver=driver,
                                     nome_thread=nome_thread,
                                     tipo_exec=tipo_exec,
                                     name_company=name_company,
                                     cnpj_cpf=username,
                                     idDoc=username,
                                     execMes=mesExec,
                                     execAno=anoExec,
                                     pastaArquivos=pastaArquivos)

                if listaParametros['nfce_emitida']:
                    exec_NFCE(driver=driver,
                              nome_thread=nome_thread,
                              name_company=name_company,
                              cnpj_cpf=username,
                              ie=ie,
                              execMes=mesExec,
                              execAno=anoExec,
                              pastaArquivos=pastaArquivos)

                sleep(1)
                limpar_pasta(pastaArquivos)

                print(f'Processo Finalizado para: ({id_company}) {name_company}')
                includeLogData(nome_thread,
                               f'PROCESSOS - {pessoa["name"]}',
                               'Processos finalizados para a pessoa...',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
                setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
                percentilInicial = percentilInicial + percentilPorPessoa

        '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
        try:
            if pasta_tem_arquivos_validos(caminho_pasta):
                shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
                includeLogData(nome_thread,
                               f'ARQUIVO FINAL',
                               'Arquivo gerado e disponível!',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
            else:
                includeLogData(nome_thread,
                               f'ARQUIVO FINAL',
                               'Nenhum arquivo gerado. ZIP não será criado.',
                               'BOT',
                               'BOT',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
            setPercentilProcesso(nome_thread, 100)
        except Exception as e:
            includeLogData(nome_thread,
                           f'ARQUIVO FINAL',
                           'Erro ao gerar arquivo!',
                           'BOT',
                           'RPA',
                           'primary-gradient',
                           'ERRO',
                           'danger')

    finally:
        '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
        sleep(3)
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        try:
            restaurar_rede_pos_sefaz(estado_rede, nome_thread)
        except Exception as e:
            print(f"Erro ao restaurar rede: {e}")


def MainExecution_Agendamentos(idAgendamento, idEstado):
    with app.app_context():
        dadosAgendamento = AgendamentosRPA.query.filter_by(id=idAgendamento).first()
        dadosAgendamento.status = 'Em Execução'
        db.session.commit()

        if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
            uf = UF.query.filter_by(id=idEstado).first()
            DPbd = (PessoaJuridica.query
                    .join(City)
                    .options(joinedload(PessoaJuridica.city))
                    .filter(PessoaJuridica.id_empresa == dadosAgendamento.id_empresa,
                            PessoaJuridica.active_mensal == True,
                            PessoaJuridica.active == True)
                    .filter(City.uf == uf.uf)
                    .all())
        elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
            uf = UF.query.filter_by(id=idEstado).first()
            DPbd = (PessoaFisica.query
                    .join(City)
                    .options(joinedload(PessoaFisica.city))
                    .filter(PessoaFisica.id_empresa == dadosAgendamento.id_empresa,
                            PessoaFisica.active_mensal == True,
                            PessoaFisica.active == True)
                    .filter(City.uf == uf.uf)
                    .all())

        ParametrosAgendamento: list[Any] = []
        for i in dadosAgendamento.processos_inclusos[1:-1].split('", "'):
            ParametrosAgendamento.append(i.replace('"', ''))

        listaPessoas = []
        for pessoa in DPbd:
            listaPessoas.append(pessoa.id)
        EmpresaExec = dadosAgendamento.id_empresa
        DataExecucao = datetime.now()

        if dadosAgendamento.in_comp_atual:
            MesExecucao = DataExecucao.month
            AnoExecucao = DataExecucao.year
        else:
            if DataExecucao.month == 1:
                MesExecucao = 12
                AnoExecucao = DataExecucao.year - 1
            else:
                MesExecucao = DataExecucao.month - 1
                AnoExecucao = DataExecucao.year

        thread_atual = threading.current_thread()
        nome_thread = thread_atual.name
        caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')

        dados = []
        desc = ''

        if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
            dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
            desc = 'pessoa jurídica'
        elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
            dados = dadosPessoasPF(listaPessoas, EmpresaExec)
            desc = 'pessoa física'

        listaLen = len(listaPessoas)
        percentilProcesso = 80
        percentilPorPessoa = int(percentilProcesso / listaLen) if listaLen else 0
        percentilInicial = 5
        setPercentilProcesso(nome_thread, percentilInicial)

        estado_rede = {}
        driver = None
        try:
            estado_rede = preparar_rede_para_sefaz(nome_thread)
            '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
            driver = IniciarDriver(nome_thread=nome_thread)
            '########## REALIZA O LOGIN UNICO SEFAZ ###########'
            dadosLogin = dadosLoginSefaz(EmpresaExec)
            logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

            if logado:
                counter = 0
                print(f'Total empresas: {len(dados)} - Agendamento {dadosAgendamento.id} - Thread: {nome_thread}')
                for pessoa in dados:

                    includeLogData(nome_thread,
                                   f'PROCESSOS - {pessoa["name"]}',
                                   f'Iniciando processos para a {desc}...',
                                   'BOT',
                                   'BOT',
                                   'primary-gradient',
                                   'SUCESSO',
                                   'success-gradient')

                    name_company = pessoa['name']
                    id_company = pessoa['id']
                    username = pessoa['username']
                    ie = pessoa['ie']

                    listaParametros = []
                    if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
                        tipo_exec = 'PJ'
                        listaParametros = checkParamPadrao('PJ', id_company)
                    elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                        tipo_exec = 'PF'
                        listaParametros = checkParamPadrao('PF', id_company)

                    '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
                    anoExec = f'{AnoExecucao}'
                    if len(str(MesExecucao)) == 1:
                        mesExec = f'0{MesExecucao}'
                    else:
                        mesExec = f'{MesExecucao}'

                    '########## VERIFICA PASTA TEMPORARIA ##########'
                    if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
                        nome_empresa = f"{name_company}"
                    elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                        nome_empresa = f"{name_company}"

                    if dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                        pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "FISCAL PJ", anoExec, mesExec,
                                                     "Relatórios")
                    else:
                        pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "FISCAL PJ", anoExec, mesExec,
                                                     "Relatórios")

                    try:
                        os.makedirs(pastaArquivos, exist_ok=True)
                        print(f"✅ Estrutura de pastas criada: {pastaArquivos}")
                    except Exception as e:
                        print(f"❌ Erro ao criar estrutura de pastas: {str(e)}")
                        raise

                    driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                           {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

                    '######### EXECUTA ESCOLHAS APOS LOGADO ########'
                    if listaParametros['nfe_saida'] and 'sefaz_nfe_saida' in ParametrosAgendamento:
                        exec_NFE_SAIDA(driver=driver,
                                       nome_thread=nome_thread,
                                       tipo_exec=tipo_exec,
                                       name_company=name_company,
                                       cnpj_cpf=username,
                                       idDoc=username if dadosAgendamento.tipo_pessoa_agendamento == 'PJ' else ie,
                                       execMes=mesExec,
                                       execAno=anoExec,
                                       pastaArquivos=pastaArquivos)
                    if listaParametros['nfe_entrada'] and 'sefaz_nfe_entrada' in ParametrosAgendamento:
                        exec_NFE_ENTRADA(driver=driver,
                                         nome_thread=nome_thread,
                                         tipo_exec=tipo_exec,
                                         name_company=name_company,
                                         cnpj_cpf=username,
                                         idDoc=username if dadosAgendamento.tipo_pessoa_agendamento == 'PJ' else ie,
                                         execMes=mesExec,
                                         execAno=anoExec,
                                         pastaArquivos=pastaArquivos)

                    if listaParametros['cte_emissor'] and 'sefaz_cte_emitido' in ParametrosAgendamento:
                        exec_CTE_EMISSOR(driver=driver,
                                         nome_thread=nome_thread,
                                         tipo_exec=tipo_exec,
                                         name_company=name_company,
                                         cnpj_cpf=username,
                                         idDoc=username if dadosAgendamento.tipo_pessoa_agendamento == 'PJ' else ie,
                                         execMes=mesExec,
                                         execAno=anoExec,
                                         pastaArquivos=pastaArquivos)

                    if listaParametros['cte_tomador'] and 'sefaz_cte_tomado' in ParametrosAgendamento:
                        exec_CTE_TOMADOR(driver=driver,
                                         nome_thread=nome_thread,
                                         tipo_exec=tipo_exec,
                                         name_company=name_company,
                                         cnpj_cpf=username,
                                         idDoc=username,
                                         execMes=mesExec,
                                         execAno=anoExec,
                                         pastaArquivos=pastaArquivos)

                    if listaParametros['nfce_emitida'] and 'sefaz_nfce' in ParametrosAgendamento:
                         exec_NFCE(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   ie=ie,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

                    sleep(1)
                    limpar_pasta(pastaArquivos)
                    includeLogData(nome_thread,
                                   f'PROCESSOS - {pessoa["name"]}',
                                   f'Processos finalizados para a {desc}...',
                                   'BOT',
                                   'BOT',
                                   'primary-gradient',
                                   'SUCESSO',
                                   'success-gradient')
                    setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
                    percentilInicial = percentilInicial + percentilPorPessoa

                    counter += 1
                    print(
                        f'Finalizado: {counter}/{len(dados)} - AgendamentoID {dadosAgendamento.id} - Thread: fetchlog-{nome_thread} - Pessoa: ({id_company}) {name_company}')

                    '######### ZIPA PASTA ESPECIFICA E ENVIA #############'

                    caminhoZip = os.path.join(caminho_pasta, nome_empresa)

                    try:
                        if pasta_tem_arquivos_validos(caminhoZip):
                            shutil.make_archive(caminhoZip, 'zip', caminhoZip)
                            includeLogData(nome_thread,
                                           f'ARQUIVO ZIP EMPRESA',
                                           'Arquivo gerado e disponível!',
                                           'BOT',
                                           'BOT',
                                           'primary-gradient',
                                           'SUCESSO',
                                           'success-gradient')
                            
                            tipo_envio = 'zip'

                            if tipo_envio == 'receiver':
                                '### ENVIA OS ARQUIVOS PARA O SERVIDOR BASE TIPO PESSOA'
                                DadosEmpresaEnvio = Empresas.query.filter_by(id=dadosAgendamento.id_empresa).first()
                                if DadosEmpresaEnvio.autorizado_schedule:
                                    pathEnvio = fr"{dadosAgendamento.path_receiver}\{nome_empresa}"
                                    receiver_ip = DadosEmpresaEnvio.receiver_ip
                                    receiver_ip_secondary = DadosEmpresaEnvio.receiver_ip_secondary
                                    receiver_port = DadosEmpresaEnvio.receiver_port
                                    zipData = os.path.join(fr"{caminhoZip}.zip")

                                    print('Iniciando envio para:')
                                    print(f'IP Primario: {receiver_ip}')
                                    print(f'IP Secundario: {receiver_ip_secondary}')
                                    print(f'Porta: {receiver_port}')
                                    print(f'zipDataPath: {zipData}')
                                    print(f'ReceiverPath: {pathEnvio}')
                                    SendRPAData(dadosAgendamento.id, zipData, receiver_ip, receiver_ip_secondary, receiver_port, pathEnvio)

                                    print('Envio Finalizado!')

                            elif tipo_envio == 'zip':
                                '### EXTRAI ARQUIVOS NO SERVIDOR BASE TIPO PESSOA'
                                pathEnvio = os.path.join(dadosAgendamento.path_receiver, nome_empresa)
                                zipData = os.path.join(fr"{caminhoZip}.zip")
                                with zipfile.ZipFile(zipData, 'r') as zip_ref:
                                    zip_ref.extractall(pathEnvio)
                        else:
                            includeLogData(nome_thread,
                                           f'ARQUIVO ZIP EMPRESA',
                                           'Nenhum arquivo gerado para zipar.',
                                           'BOT',
                                           'BOT',
                                           'warning-gradient',
                                           'ATENÇÃO',
                                           'warning-gradient')
                        setPercentilProcesso(nome_thread, 100)
                    except Exception as e:
                        print(f"Ocorreu um erro ao zipar a pasta: {e}")
                        includeLogData(nome_thread,
                                       f'ARQUIVO ZIP EMPRESA',
                                       'Erro ao gerar arquivo!',
                                       'BOT',
                                       'RPA',
                                       'primary-gradient',
                                       'ERRO',
                                       'danger-gradient')

            dadosAgendamento = AgendamentosRPA.query.filter_by(id=idAgendamento).first()
            if dadosAgendamento.in_repeat:
                dadosAgendamento.status = 'Aguardando Próxima Execução'
            else:
                dadosAgendamento.status = 'Execução Finalizada'
            db.session.commit()

            print(f'Finalizou Execução do item agendado. (ID:{dadosAgendamento.id})')
            sleep(5)
            print('Iniciando envio dos arquivos do agendamento.')
            sleep(5)

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            try:
                restaurar_rede_pos_sefaz(estado_rede, nome_thread)
            except Exception as e:
                print(f"Erro ao restaurar rede: {e}")


def dadosPessoasPF(listaPessoas, EmpresaExec):
    with app.app_context():
        dadospessoas = []

        for id_pessoa in listaPessoas:
            DPbd = PessoaFisica.query.options(joinedload(PessoaFisica.city)).filter_by(id_empresa=EmpresaExec,
                                                                                       id=id_pessoa).first()
            dadospessoas.append(
                {
                    "name": DPbd.name,
                    "id": DPbd.id,
                    "username": DPbd.cnpj_cpf,
                    "ie": DPbd.ie,
                    "password": DPbd.password,
                    "cidade": DPbd.city.name,
                }
            )
    return dadospessoas


def dadosPessoasPJ(listaPessoas, EmpresaExec):
    with app.app_context():
        dadospessoas = []

        for id_pessoa in listaPessoas:
            DPbd = PessoaJuridica.query.options(joinedload(PessoaJuridica.city)).filter_by(id_empresa=EmpresaExec,
                                                                                           id=id_pessoa).first()
            dadospessoas.append(
                {
                    "name": DPbd.name,
                    "id": DPbd.id,
                    "username": DPbd.cnpj_cpf,
                    "ie": DPbd.ie,
                    "password": DPbd.password,
                    "cidade": DPbd.city.name,
                }
            )
    return dadospessoas


def click_element_cdp(driver, element):
    """Executa um clique nativo do mouse via CDP (isTrusted = True)."""
    # Scroll the element into view
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    sleep(0.3)
    
    # Get element position relative to viewport
    rect = driver.execute_script("""
        var rect = arguments[0].getBoundingClientRect();
        return {
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2
        };
    """, element)
    
    x = int(rect['x'])
    y = int(rect['y'])
    
    # Move mouse to position
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseMoved",
        "x": x,
        "y": y
    })
    sleep(0.1)
    
    # Mouse press
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mousePressed",
        "button": "left",
        "clickCount": 1,
        "x": x,
        "y": y
    })
    sleep(0.1)
    
    # Mouse release
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {
        "type": "mouseReleased",
        "button": "left",
        "clickCount": 1,
        "x": x,
        "y": y
    })
    sleep(0.1)


def obter_versao_chrome() -> str:
 # Remove chamadas ao subprocess para evitar UnicodeDecodeError no Windows
 return "Ignorado para evitar erros de terminal"


def obter_versao_chromedriver() -> str:
 # Remove chamadas ao subprocess para evitar UnicodeDecodeError no Windows
 return "Ignorado para evitar erros de terminal"


def IniciarDriver(nome_thread=None, usar_extensao=False):
 import tempfile
 import uuid
 import shutil as _shutil

 chrome_driver_path = os.path.join(
  root_path,
  r"OnixWeb\rpautomation\dependencias\chromedriver\chromedriver.exe"
 )

 if not os.path.exists(chrome_driver_path):
  raise FileNotFoundError(f"ChromeDriver não encontrado em: {chrome_driver_path}")

 safe_thread = re.sub(r"[^a-zA-Z0-9_-]", "_", str(nome_thread or "BOT"))

 debug_dir = os.path.join(root_path, "debug_sefaz")
 os.makedirs(debug_dir, exist_ok=True)

 log_path = os.path.join(
  debug_dir,
  f"chromedriver_{safe_thread}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
 )

 perfil_chrome = os.path.join(
  tempfile.gettempdir(),
  f"onix_sefaz_profile_{safe_thread}_{uuid.uuid4().hex}"
 )
 os.makedirs(perfil_chrome, exist_ok=True)

 service = Service(
  executable_path=chrome_driver_path,
  log_output=log_path
 )

 chrome_options = Options()

 chrome_options.add_argument("--start-maximized")
 chrome_options.add_argument("--no-first-run")
 chrome_options.add_argument("--no-default-browser-check")
 chrome_options.add_argument("--disable-popup-blocking")
 chrome_options.add_argument("--disable-notifications")

 # Perfil isolado por thread/execução
 chrome_options.add_argument(f"--user-data-dir={perfil_chrome}")

 # Estabilidade
 chrome_options.add_argument("--remote-debugging-port=0")
 chrome_options.add_argument("--disable-dev-shm-usage")
 chrome_options.add_argument("--disable-gpu")

 # Reduz serviços Google em background
 chrome_options.add_argument("--disable-background-networking")
 chrome_options.add_argument("--disable-sync")
 chrome_options.add_argument("--disable-component-update")
 chrome_options.add_argument("--disable-default-apps")

 # Automação
 chrome_options.add_argument("--disable-blink-features=AutomationControlled")
 chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
 chrome_options.add_experimental_option("useAutomationExtension", False)

 if usar_extensao:
  chrome_extension_path = os.path.join(
   root_path,
   "OnixWeb",
   "rpautomation",
   "dependencias",
   "chrome_extension"
  )
  if os.path.exists(chrome_extension_path):
   chrome_options.add_argument(f"--load-extension={chrome_extension_path}")
  else:
   print(f"Caminho da extensao nao encontrado: {chrome_extension_path}")
 else:
  chrome_options.add_argument("--disable-extensions")

 prefs = {
  "plugins.always_open_pdf_externally": True,
  "credentials_enable_service": False,
  "download.prompt_for_download": False,
  "download.directory_upgrade": True,
  "profile.password_manager_enabled": False,
  "safebrowsing.enabled": True
 }
 chrome_options.add_experimental_option("prefs", prefs)

 try:
  driver = webdriver.Chrome(service=service, options=chrome_options)
 except WebDriverException as e:
  print(f"Erro ao iniciar Chrome. Veja o log do ChromeDriver em: {log_path}")
  try:
   _shutil.rmtree(perfil_chrome, ignore_errors=True)
  except Exception:
   pass
  raise

 try:
  stealth(
   driver,
   languages=["pt-BR", "pt"],
   vendor="Google Inc.",
   platform="Win32",
   webgl_vendor="Intel Inc.",
   renderer="Intel Iris OpenGL Engine",
   fix_hairline=True,
  )
 except Exception as e:
  print(f"Falha ao aplicar stealth, seguindo mesmo assim: {e}")

 try:
  driver.set_page_load_timeout(60)
  driver.set_script_timeout(60)
 except Exception:
  pass

 return driver


_stop_watcher = False

def find_chrome_hwnds():
    hwnd_list = []
    import ctypes
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    GetWindowText = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible

    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            buff = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, buff, 256)
            class_name = buff.value
            if class_name == "Chrome_WidgetWin_1":
                length = GetWindowTextLength(hwnd)
                title_buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, title_buff, length + 1)
                title = title_buff.value
                if title:
                    hwnd_list.append(hwnd)
        return True
    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return hwnd_list


def auto_press_enter_on_chrome_watcher(nome_thread=None):
    """Loop em segundo plano que ativa o Chrome e envia ENTER para selecionar o certificado digital."""
    global _stop_watcher
    print(f"[{nome_thread or 'BOT'}] Watcher de Certificado Digital iniciado em segundo plano...")
    import time
    import ctypes
    
    # Aguarda o navegador abrir e iniciar a conexão TLS
    time.sleep(4.0)
    
    KEYEVENTF_KEYUP = 0x0002
    VK_RETURN = 0x0D
    
    attempts = 0
    while not _stop_watcher and attempts < 10:
        attempts += 1
        try:
            hwnds = find_chrome_hwnds()
            if hwnds:
                for hwnd in hwnds:
                    # Traz o Chrome para o primeiro plano
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    time.sleep(0.5)
                    # Envia ENTER
                    ctypes.windll.user32.keybd_event(VK_RETURN, 0, 0, 0)
                    time.sleep(0.1)
                    ctypes.windll.user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
        except Exception as e:
            print(f"Erro no watcher de certificado: {e}")
        time.sleep(3.0)
    print(f"[{nome_thread or 'BOT'}] Watcher de Certificado Digital finalizado.")


def exec_LOGIN_CERTIFICADO(driver, nome_thread):
    global _stop_watcher
    _stop_watcher = False
    
    includeLogData(nome_thread,
                   f'LOGIN - CERTIFICADO',
                   f'Realizando login via Certificado Digital...',
                   f'BOT',
                   'SEFAZ',
                   'warning-gradient',
                   'ATENÇÃO',
                   'warning-gradient')
                   
    # Inicia o watcher em segundo plano
    watcher_thread = threading.Thread(target=auto_press_enter_on_chrome_watcher, args=(nome_thread,), daemon=True)
    watcher_thread.start()
    
    url = "https://www.sefaz.mt.gov.br/acesso/pages/login-certificado/login-certificado.xhtml"
    logado = False
    import random
    
    try:
        if not abrir_url_sefaz(driver, url, nome_thread, tentativas=5, timeout=45):
            print("Erro ao carregar pagina de login por certificado da SEFAZ.")
            return False
            
        # Espera um respiro para a handshake completar
        sleep(2.0)
        
        if pagina_tem_erro_conexao(driver):
            print("Erro de conexao na pagina de certificado.")
            return False
            
        # Selecionar Tipo de Usuário "Contabilista"
        try:
            select_label = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="j_idt34:selectTipoUsuario_label"]'))
            )
            click_element_cdp(driver, select_label)
            sleep(random.uniform(0.5, 1.0))

            select_option = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="j_idt34:selectTipoUsuario_1"]'))
            )
            click_element_cdp(driver, select_option)
            sleep(random.uniform(1.0, 2.0))
            
            # Clicar no botão Efetuar Login (que é um input do tipo submit)
            btn_entrar = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' and contains(@class, 'btnPadrao')]"))
            )
            click_element_cdp(driver, btn_entrar)
            print("Botao de login via certificado clicado. Aguardando redirecionamento...")
            sleep(random.uniform(3.0, 5.0))
            
        except Exception as e:
            print(f"Erro ao interagir com campos de login certificado: {e}")
            
        # Verificar se redirecionou para paginainicial.xhtml
        try:
            pagina_inicial_logado = 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'
            WebDriverWait(driver, 15).until(EC.url_contains('paginainicial.xhtml'))
            logado = True
        except Exception:
            logado = False
            print("Nao redirecionou para a pagina inicial apos login por certificado.")
            
    finally:
        _stop_watcher = True
        
    if logado:
        includeLogData(nome_thread,
                       'LOGIN - CERTIFICADO',
                       'Acesso realizado com sucesso via Certificado Digital.',
                       'BOT',
                       'SEFAZ',
                       'warning-gradient',
                       'SUCESSO',
                       'success-gradient')
        print('logou SEFAZ via Certificado Digital')
        return True
        
    return False


def exec_LOGIN(driver, nome_thread, login_sefaz_contabilista, senha_sefaz_contabilista):
    if USAR_CERTIFICADO_SEFAZ:
        return exec_LOGIN_CERTIFICADO(driver, nome_thread)

    # Normalizar logins do tipo MTXXXXXXOOX para MTXXXXXXooX
    if login_sefaz_contabilista and isinstance(login_sefaz_contabilista, str):
        if login_sefaz_contabilista.startswith("MT"):
            login_sefaz_contabilista = login_sefaz_contabilista.replace("OO", "oo")

    includeLogData(nome_thread,
                   f'LOGIN - CONTABILISTA',
                   f'Realizando login...',
                   f'BOT',
                   'SEFAZ',
                   'warning-gradient',
                   'ATENÇÃO',
                   'warning-gradient')
    sefaz = 'https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml'

    if not abrir_url_sefaz(driver, sefaz, nome_thread):
        print("Erro ao carregar pagina de login da SEFAZ.")
        return False

    import random
    inicio = time()
    max_tentativas_captcha = 10
    timeout_login_total = 180
    logado = False

    for tentativa in range(1, max_tentativas_captcha + 1):
        if time() - inicio > timeout_login_total:
            print("Timeout do login total excedido.")
            break

        print(f"Tentativa de login {tentativa}/{max_tentativas_captcha}...")
        try:
            current_url = driver.current_url or ""
            if "login.xhtml" not in current_url or pagina_tem_erro_conexao(driver):
                if not abrir_url_sefaz(driver, sefaz, nome_thread):
                    continue

            # Selecionar tipo Contabilista
            try:
                select_label = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="formLogin:selectTipoUsuario_label"]'))
                )
                click_element_cdp(driver, select_label)
                sleep(random.uniform(0.5, 1.0))

                select_option = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="formLogin:selectTipoUsuario_1"]'))
                )
                click_element_cdp(driver, select_option)
                sleep(random.uniform(1.0, 2.0))
            except Exception as e:
                print(f"Erro ao selecionar tipo usuario: {e}")

            # Obter o src atual antes de atualizar
            old_src = ""
            try:
                img_element = driver.find_element(By.XPATH, '//*[@id="formLogin:superPanel"]/div[3]/div/img')
                old_src = img_element.get_attribute("src") or ""
            except Exception:
                pass

            # Atualizar captcha
            try:
                campoAtualizaCaptcha = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[text()='Clique aqui se não visualizar a imagem.']"))
                )
                click_element_cdp(driver, campoAtualizaCaptcha)
                sleep(random.uniform(1.0, 2.0))
            except Exception:
                pass
            
            # Obter imagem do captcha (esperando carregar além do placeholder e mudar do anterior)
            base64_link = ""
            for i in range(50):
                try:
                    img_element = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="formLogin:superPanel"]/div[3]/div/img'))
                    )
                    src = img_element.get_attribute("src") or ""
                    if len(src) > 1000 and src.startswith("data:image/") and src != old_src:
                        base64_link = src
                        break
                except Exception:
                    pass
                sleep(0.1)

            if not base64_link:
                print("Nao foi possivel carregar uma imagem de captcha valida.")
                sleep(1.0)
                continue

            captcha = resolver_captcha_base64(base64_link, nome_thread)
            if not captcha:
                print("Nao foi possivel resolver o captcha nesta tentativa.")
                sleep(1.0)
                continue
                
            print(f"Captcha obtido: {captcha}")
            
            # Preencher Login
            inp_login = driver.find_element(By.XPATH, '//*[@id="formLogin:inputLogin"]')
            inp_login.clear()
            for ch in login_sefaz_contabilista:
                inp_login.send_keys(ch)
                sleep(random.uniform(0.06, 0.14))
            sleep(random.uniform(0.4, 0.8))
            
            # Preencher Senha
            inp_senha = driver.find_element(By.XPATH, '//*[@id="formLogin:inputSenha"]')
            inp_senha.clear()
            for ch in senha_sefaz_contabilista:
                inp_senha.send_keys(ch)
                sleep(random.uniform(0.06, 0.14))
            sleep(random.uniform(0.4, 0.8))
            
            # Preencher Captcha
            inp_captcha = driver.find_element(By.XPATH, '//*[@id="formLogin:inputCaptcha"]')
            inp_captcha.clear()
            for ch in captcha:
                inp_captcha.send_keys(ch)
                sleep(random.uniform(0.06, 0.14))
            sleep(random.uniform(0.8, 1.5))
            
            # Clicar no botão Efetuar Login
            submit_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'btnPadrao')]"))
            )
            click_element_cdp(driver, submit_btn)
            
            print("Formulario submetido. Aguardando resposta...")
            sleep(random.uniform(3.0, 5.0))
            
            try:
                pagina_inicial_logado = 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'
                WebDriverWait(driver, 10).until(EC.url_to_be(pagina_inicial_logado))
                logado = True
                break
            except Exception:
                logado = False
                print("Ainda nao logou. Tentando novamente...")
                sleep(random.uniform(2.0, 4.0))
                
        except Exception as e:
            print(f"Erro na tentativa {tentativa}: {e}")
            sleep(2.0)

    if logado:
        includeLogData(nome_thread,
                       'LOGIN - CONTABILISTA',
                       'Acesso realizado com sucesso.',
                       'BOT',
                       'SEFAZ',
                       'warning-gradient',
                       'SUCESSO',
                       'success-gradient')
        print('logou SEFAZ')
        return True

    if AUTO_FALLBACK_LOGIN_MANUAL:
        print("Iniciando login manual assistido por falha no OCR.")
        return exec_LOGIN_MANUAL(driver, nome_thread, timeout=300)

    return False


def hide_overlay_if_any(driver):
    try:
        driver.execute_script("var m=document.querySelector('[id*=\"_modal\"]'); if(m){m.style.display='none';}")
    except Exception:
        pass


def _is_accountant_not_rep(msg: str) -> bool:
    if not msg:
        return False
    norm = " ".join(msg.split())
    return norm.startswith("Erro Contabilista não representa o Contribuinte:")


def _screenshot_if_accountant_dialog(driver, pastaArquivos, filename="NFe-Sem-Saida e Entrada.png"):
    """
    Procura o diálogo PrimeFaces (primefacesmessagedlg) e verifica o conteúdo real do diálogo.
    Se contiver 'Contabilista não representa o Contribuinte', tira screenshot, fecha e retorna True.
    Caso contrário, retorna False.
    """
    try:
        dlg = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.XPATH, "//*[@id='primefacesmessagedlg']"))
        )
        if not dlg.is_displayed():
            return False
        try:
            content = dlg.find_element(By.XPATH, ".//div[contains(@class,'ui-dialog-content')]")
            dlg_text = (content.text or "").strip()
        except Exception:
            dlg_text = (dlg.text or "").strip()
        if "Contabilista não representa o Contribuinte" in dlg_text:
            try:
                destino = f"{pastaArquivos}/{filename}"
                if os.path.exists(destino):
                    os.remove(destino)
                driver.save_screenshot(destino)
            except Exception:
                pass
            # fecha o diálogo
            try:
                close_btn = dlg.find_element(By.XPATH, ".//div[1]/a/span")
                if close_btn.is_displayed():
                    close_btn.click()
                    sleep(0.2)
            except Exception:
                pass
            return True
    except Exception:
        pass
    return False


def get_and_close_errors(driver, close_dialog=True, wait_seconds=0.0):
    """
    Retorna lista de mensagens de erro PrimeFaces visíveis na tela.
    - Captura erros inline (aria-live='polite' com classes ui-message ui-message-error).
    - Captura erros em dialog (primefacesmessagedlg).
    - Opcionalmente tenta fechar o dialog (botão X).
    """
    if wait_seconds and wait_seconds > 0:
        end_t = time() + wait_seconds
        while time() < end_t:
            sleep(0.05)

    errors = []

    try:
        containers = driver.find_elements(
            By.XPATH,
            "//*[@aria-live='polite' and contains(@class,'ui-message') and contains(@class,'ui-message-error')]"
        )
        for c in containers:
            if c.is_displayed():
                txt = (c.text or "").strip()
                if txt:
                    errors.append(txt)
    except Exception:
        pass

    try:
        spans = driver.find_elements(
            By.XPATH,
            "//span[contains(@class,'ui-message-error-detail')]"
        )
        for s in spans:
            if s.is_displayed():
                txt = (s.text or "").strip()
                if txt and txt not in errors:
                    errors.append(txt)
    except Exception:
        pass

    try:
        dlg = driver.find_element(By.XPATH, "//*[@id='primefacesmessagedlg']")
        if dlg.is_displayed():
            txt = (dlg.text or "").strip()
            if txt:
                lines = [l.strip() for l in txt.splitlines() if l.strip()]
                dlg_msg = " ".join(lines).strip()
                if dlg_msg and dlg_msg not in errors:
                    errors.append(dlg_msg)
            if close_dialog:
                try:
                    close_btn = dlg.find_element(By.XPATH, ".//div[1]/a/span")
                    if close_btn.is_displayed():
                        close_btn.click()
                        sleep(0.2)
                except Exception:
                    pass
    except Exception:
        pass

    return errors


def exec_NFE_SAIDA(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    consultas = 'https://www.sefaz.mt.gov.br/nfe/pages/consultaemitidasrecebidas/consultaemitidasrecebidas.xhtml'
    possuiregistrosSaidas = False

    # Navega para a página
    if not abrir_url_sefaz(driver, consultas, nome_thread):
        return

    # Seleciona EMISSOR
    try:
        FlagEmissor = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'sorEmissorDest')]/tbody/tr/td[1]/div/div[2]"))
        )
        FlagEmissor.click()
        sleep(0.5)
    except Exception:
        try:
            FlagEmissorAlt = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'sorEmissorDest')]//*[contains(@class,'ui-radiobutton')][1]"))
            )
            FlagEmissorAlt.click()
            sleep(0.5)
        except Exception:
            pass

    # Tipo de documento (PF/PJ)
    campoTipoDocumento = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "label[id$=':tipoDoct_label']")))
    campoTipoDocumento.click()
    sleep(0.2)
    if tipo_exec == 'PJ':
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'tipoDoct_1')]"))
        ).click()
    elif tipo_exec == 'PF':
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'tipoDoct_0')]"))
        ).click()

    sleep(0.2)
    hide_overlay_if_any(driver)

    # Documento (idDoc)
    campoInput = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id$=':numrDoct']")))
    campoInput.click()
    sleep(0.2)
    for char in f'{idDoc}':
        campoInput.send_keys(char)
        sleep(0.08)
    sleep(0.2)
    actions.send_keys(Keys.TAB).perform()
    sleep(1.0)

    # Datas
    mes = int(execMes)
    ano = int(execAno)
    inicio_mes_dt = datetime(ano, mes, 1)
    if mes == 12:
        fim_mes_dt = datetime(ano, mes, day=31)
    else:
        fim_mes_dt = datetime(ano, mes + 1, 1) + timedelta(days=-1)
    inicio_mes = inicio_mes_dt.strftime("%d/%m/%Y")
    fim_mes = fim_mes_dt.strftime("%d/%m/%Y")

    campoDtInicial = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'dataInicial_input')]")))
    for char in f'{inicio_mes}':
        campoDtInicial.send_keys(char)
    sleep(0.2)
    actions.send_keys(Keys.TAB).perform()
    campoDtFinal = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'dataFinal_input')]")))
    for char in f'{fim_mes}':
        campoDtFinal.send_keys(char)
    sleep(0.2)

    # Consultar
    hide_overlay_if_any(driver)
    campoConsulta = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'btnConsEmitReceb')]")))
    campoConsulta.click()
    sleep(0.3)

    if _screenshot_if_accountant_dialog(driver, pastaArquivos, "NFe-Sem-Saida e Entrada.png"):
        try:
            includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                           f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
        except Exception:
            pass
        return

    errors = get_and_close_errors(driver, close_dialog=True, wait_seconds=0.5)

    if any("Contabilista não representa o Contribuinte" in e for e in errors):
        try:
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
            if os.path.exists(pasta_destino): os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
        except Exception:
            pass
        errors = [e for e in errors if "Contabilista não representa o Contribuinte" not in e]
        try:
            includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                           f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
        except Exception:
            pass
        return

    tentativas = 0
    max_tentativas = 5
    while errors and tentativas < max_tentativas:
        tentativas += 1
        try:
            campoDtInicial = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id$=':dataInicial_input']")))
            campoDtFinal = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id$=':dataFinal_input']")))
            for elm, valor in [(campoDtInicial, inicio_mes), (campoDtFinal, fim_mes)]:
                elm.click()
                actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                elm.send_keys(Keys.DELETE); sleep(0.1)
                for ch in valor: elm.send_keys(ch)
                sleep(0.2)
            hide_overlay_if_any(driver)
            campoConsulta = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'btnConsEmitReceb')]"))
            )
            campoConsulta.click()
            sleep(0.3)

            if _screenshot_if_accountant_dialog(driver, pastaArquivos, "NFe-Sem-Saida e Entrada.png"):
                try:
                    includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                                   f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
                except Exception:
                    pass
                return
        except Exception:
            sleep(0.3)

        errors = get_and_close_errors(driver, close_dialog=True, wait_seconds=0.5)
        if any("Contabilista não representa o Contribuinte" in e for e in errors):
            try:
                pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
                if os.path.exists(pasta_destino): os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
            except Exception:
                pass
            try:
                dlg = driver.find_element(By.XPATH, "//*[@id='primefacesmessagedlg']")
                if dlg.is_displayed():
                    try:
                        close_btn = dlg.find_element(By.XPATH, ".//div[1]/a/span")
                        if close_btn.is_displayed():
                            close_btn.click()
                            sleep(0.2)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                               f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
            except Exception:
                pass
            return

    if errors:
        try:
            includeLogData(
                nome_thread,
                f'NFe - {name_company}',
                f'Erro(s) na consulta: ' + " | ".join(errors),
                f'{cnpj_cpf}',
                'SEFAZ',
                'danger-gradient',
                'ERRO',
                'danger-gradient'
            )
        except Exception:
            pass
        return

    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="primefacesmessagedlg"]')))
        msgerro = driver.find_element(By.XPATH, '//*[@id="primefacesmessagedlg"]')
        if msgerro.get_attribute("aria-live") == 'polite':
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.find_element(By.XPATH, '//*[@id="primefacesmessagedlg"]/div[1]/a/span').click()
            possuiregistrosSaidas = False

        includeLogData(nome_thread,
                       f'NFe - {name_company}',
                       f'Pessoa não possui NFes de Saída/Entrada.',
                       f'{cnpj_cpf}',
                       'SEFAZ',
                       'warning-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
    except Exception:
        possuiregistrosSaidas = True

    try:
        nenhumRegistroSaidas = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'dtResultCons_data')]/tr/td")))
        textoRegistro = (nenhumRegistroSaidas.get_attribute("textContent") or "").strip()
        if textoRegistro == 'Nenhuma NF-e foi encontrada':
            blockDadosConsultas = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'tabDadosCons')]")))
            driver.execute_script("arguments[0].style.setProperty('display', 'block', 'important');", blockDadosConsultas)
            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Saidas.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")
            possuiregistrosSaidas = False
            try:
                includeLogData(nome_thread,
                               f'NFe - {name_company}',
                               f'Pessoa não possui NFes de Saída.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
            except Exception:
                pass
        else:
            possuiregistrosSaidas = True
    except Exception:
        pass

    if possuiregistrosSaidas:
        try:
            CampoDownload = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='Exportar para Excel']")))
            CampoDownload.click()
        except Exception as e:
            print('error#3'); print(e)
        sleep(2)

        if not abrir_url_sefaz(driver, consultas, nome_thread):
            return
        sleep(8)

        arquivoSaida = fr'{pastaArquivos}\Sefaz-Saidas.xls'
        arquivos_filtrados = []
        arquivos_xls = glob.glob(os.path.join(pastaArquivos, '*.xls'))
        for arquivo in arquivos_xls:
            if 'Sefaz-Saidas' in arquivo:
                os.remove(arquivo)
            elif 'Sefaz-Entradas' in arquivo:
                os.remove(arquivo)
            elif 'ConsultaNFeEmitidasRecebidas' in arquivo:
                arquivos_filtrados.append(arquivo)

        for arquivo in arquivos_filtrados:
            os.rename(arquivo, arquivoSaida)

        try:
            includeLogData(nome_thread,
                           f'NFe - {name_company}',
                           f'Arquivos (Excel) NFes de Saída baixado com sucesso.',
                           f'{cnpj_cpf}',
                           'SEFAZ',
                           'warning-gradient',
                           'SUCESSO',
                           'success-gradient')
        except Exception:
            pass


def exec_NFE_ENTRADA(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    possuiregistrosEntradas = True
    consultas = 'https://www.sefaz.mt.gov.br/nfe/pages/consultaemitidasrecebidas/consultaemitidasrecebidas.xhtml'

    if not abrir_url_sefaz(driver, consultas, nome_thread):
        return

    try:
        FlagDestinatario = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'sorEmissorDest')]/tbody/tr/td[2]/div/div[2]"))
        )
        FlagDestinatario.click()
    except Exception as e:
        print('error#4'); print(e)
    sleep(0.5)

    campoTipoDocumento = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "label[id$=':tipoDoct_label']")))
    campoTipoDocumento.click()
    sleep(0.2)
    if tipo_exec == 'PJ':
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'tipoDoct_1')]"))
        ).click()
    elif tipo_exec == 'PF':
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'tipoDoct_0')]"))
        ).click()

    sleep(0.2)
    hide_overlay_if_any(driver)

    campoInput = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id$=':numrDoct']")))
    campoInput.click()
    sleep(0.2)
    for char in f'{idDoc}':
        campoInput.send_keys(f'{char}')
        sleep(0.1)
    sleep(0.2)
    actions.send_keys(Keys.TAB).perform()
    sleep(3)

    mes = int(execMes)
    ano = int(execAno)
    inicio_mes_dt = datetime(ano, mes, 1)
    if mes == 12:
        fim_mes_dt = datetime(ano, mes, day=31)
    else:
        fim_mes_dt = datetime(ano, mes + 1, 1) + timedelta(days=-1)
    inicio_mes = inicio_mes_dt.strftime("%d/%m/%Y")
    fim_mes = fim_mes_dt.strftime("%d/%m/%Y")

    campoDtInicial = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'dataInicial_input')]")))
    for char in f'{inicio_mes}':
        campoDtInicial.send_keys(char)
    sleep(0.2)
    actions.send_keys(Keys.TAB).perform()
    campoDtFinal = WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'dataFinal_input')]")))
    for char in f'{fim_mes}':
        campoDtFinal.send_keys(char)
    sleep(0.2)

    hide_overlay_if_any(driver)
    campoConsulta = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'btnConsEmitReceb')]")))
    campoConsulta.click()
    sleep(0.3)

    if _screenshot_if_accountant_dialog(driver, pastaArquivos, "NFe-Sem-Saida e Entrada.png"):
        try:
            includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                           f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
        except Exception:
            pass
        return

    errors = get_and_close_errors(driver, close_dialog=True, wait_seconds=0.5)

    if any("Contabilista não representa o Contribuinte" in e for e in errors):
        try:
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
            if os.path.exists(pasta_destino): os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
        except Exception:
            pass
        errors = [e for e in errors if "Contabilista não representa o Contribuinte" not in e]
        try:
            includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                           f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
        except Exception:
            pass
        return

    tentativas = 0
    max_tentativas = 5
    while errors and tentativas < max_tentativas:
        tentativas += 1
        try:
            campoDtInicial = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id$=':dataInicial_input']")))
            campoDtFinal = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id$=':dataFinal_input']")))
            for elm, valor in [(campoDtInicial, inicio_mes), (campoDtFinal, fim_mes)]:
                elm.click()
                actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                elm.send_keys(Keys.DELETE); sleep(0.1)
                for ch in valor: elm.send_keys(ch)
                sleep(0.2)
            hide_overlay_if_any(driver)
            campoConsulta = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(@id, 'btnConsEmitReceb')]"))
            )
            campoConsulta.click()
            sleep(0.3)

            if _screenshot_if_accountant_dialog(driver, pastaArquivos, "NFe-Sem-Saida e Entrada.png"):
                try:
                    includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                                   f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
                except Exception:
                    pass
                return
        except Exception:
            sleep(0.3)

        errors = get_and_close_errors(driver, close_dialog=True, wait_seconds=0.5)
        if any("Contabilista não representa o Contribuinte" in e for e in errors):
            try:
                pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
                if os.path.exists(pasta_destino): os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
            except Exception:
                pass
            try:
                dlg = driver.find_element(By.XPATH, "//*[@id='primefacesmessagedlg']")
                if dlg.is_displayed():
                    try:
                        close_btn = dlg.find_element(By.XPATH, ".//div[1]/a/span")
                        if close_btn.is_displayed():
                            close_btn.click()
                            sleep(0.2)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                includeLogData(nome_thread, f'NFe - {name_company}', 'Pessoa não possui NFes de Saída/Entrada.',
                               f'{cnpj_cpf}', 'SEFAZ', 'warning-gradient', 'ATENÇÃO', 'warning-gradient')
            except Exception:
                pass
            return

    if errors:
        try:
            includeLogData(
                nome_thread,
                f'NFe - {name_company}',
                f'Erro(s) na consulta: ' + " | ".join(errors),
                f'{cnpj_cpf}',
                'SEFAZ',
                'danger-gradient',
                'ERRO',
                'danger-gradient'
            )
        except Exception:
            pass
        return

    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="primefacesmessagedlg"]')))
        msgerro = driver.find_element(By.XPATH, '//*[@id="primefacesmessagedlg"]')
        if msgerro.get_attribute("aria-live") == 'polite':
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.find_element(By.XPATH, '//*[@id="primefacesmessagedlg"]/div[1]/a/span').click()
        possuiregistrosEntradas = False
        try:
            includeLogData(nome_thread,
                           f'NFe - {name_company}',
                           f'Pessoa não possui NFes de Saída/Entrada.',
                           f'{cnpj_cpf}',
                           'SEFAZ',
                           'warning-gradient',
                           'ATENÇÃO',
                           'warning-gradient')
        except Exception:
            pass
    except Exception:
        sleep(0.2)

    try:
        nenhumRegistroEntradas = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'dtResultCons_data')]/tr/td")))
        textoRegistro = (nenhumRegistroEntradas.get_attribute("textContent") or "").strip()
        if textoRegistro == 'Nenhuma NF-e foi encontrada':
            blockDadosConsultas = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'tabDadosCons')]")))
            driver.execute_script("arguments[0].style.setProperty('display', 'block', 'important');", blockDadosConsultas)
            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Entradas.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")
            possuiregistrosEntradas = False
            sleep(0.5)
            try:
                includeLogData(nome_thread,
                               f'NFe - {name_company}',
                               f'Pessoa não possui NFes de Entrada.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
            except Exception:
                pass
    except Exception:
        sleep(0.2)

    if possuiregistrosEntradas:
        try:
            CampoDownload = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//*[text()='Exportar para Excel']")))
            CampoDownload.click()
        except Exception:
            pass
        sleep(8)

        arquivoEntrada = fr'{pastaArquivos}\Sefaz-Entradas.xls'
        if os.path.exists(arquivoEntrada):
            os.remove(arquivoEntrada)

        arquivos_filtrados2 = []
        arquivos_xls2 = glob.glob(os.path.join(pastaArquivos, '*.xls'))
        for arquivo in arquivos_xls2:
            if 'ConsultaNFeEmitidasRecebidas' in arquivo:
                arquivos_filtrados2.append(arquivo)

        for arquivo in arquivos_filtrados2:
            os.rename(arquivo, arquivoEntrada)

        try:
            includeLogData(nome_thread,
                           f'NFe - {name_company}',
                           f'Arquivos (Excel) NFes de Entrada baixado com sucesso.',
                           f'{cnpj_cpf}',
                           'SEFAZ',
                           'warning-gradient',
                           'SUCESSO',
                           'success-gradient')
        except Exception:
            pass


def exec_CTE_EMISSOR(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    temregistrosCTE = False
    if not temregistrosCTE:
        try:
            consultascte = 'https://www.sefaz.mt.gov.br/cte/portal/consultaremitidorecebido'
            if not abrir_url_sefaz(driver, consultascte, nome_thread):
                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Erro ao carregar consulta de CTe (Sefaz).',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ERRO',
                               'danger-gradient')
                temregistrosCTE = False
                return

            try:
                msg_erro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, f"SEFAZ-FONT-MensagemErro")))
                if msg_erro:
                    pasta_destino = f"{pastaArquivos}/Erro CTE Sefaz.png"
                    if os.path.exists(pasta_destino):
                        os.remove(pasta_destino)
                    driver.save_screenshot(pasta_destino)

                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Consulta de CTe fora do ar (Sefaz).',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ERRO',
                               'danger-gradient')
                temregistrosCTE = False
            except Exception as e:
                pass

            campoTipo = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                (By.XPATH, '//*[@id="tipoConsulta"]')))

            selectTipo = Select(campoTipo)
            selectTipo.select_by_visible_text('Emissor')

            campoIdentificacao = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                (By.XPATH, '//*[@id="idenEmissor"]')))
            selectIdentificacao = Select(campoIdentificacao)

            if tipo_exec == 'PJ':
                selectIdentificacao.select_by_visible_text('CNPJ')

                campoIdentificacaoInput = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="campoCnpjEmissor"]')))

                campoIdentificacaoInput.send_keys(f"{idDoc}")
            elif tipo_exec == 'PF':
                selectIdentificacao.select_by_visible_text('Inscrição Estadual')

                campoIdentificacaoInput = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="campoIeEmissor"]')))

                campoIdentificacaoInput.send_keys(f"{idDoc}")

            sleep(0.5)
            mes = int(execMes)
            ano = int(execAno)
            inicio_mes = datetime(ano, mes, 1)
            if mes == 12:
                fim_mes = datetime(ano, mes, day=31)
            else:
                fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
            inicio_mes = inicio_mes.strftime("%d/%m/%Y")
            fim_mes = fim_mes.strftime("%d/%m/%Y")

            actions.send_keys(Keys.TAB).perform()
            sleep(3)
            actions.send_keys(inicio_mes).perform()
            sleep(0.2)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.2)
            actions.send_keys(fim_mes).perform()
            sleep(1)
            campoConsulta = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="btnConsultar"]')))
            campoConsulta.click()

            try:
                continua_carregando = True
                tempo_carregando = 0
                while continua_carregando:
                    carregando = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.NAME, 'imgCarregando')))
                    if tempo_carregando < 120:
                        value_carregando = carregando.size['width']
                        if value_carregando > 0:
                            sleep(1)
                            tempo_carregando += 1
                        else:
                            continua_carregando = False
                    elif tempo_carregando >= 120:
                        on_consultas = False
                        while not on_consultas:
                            try:
                                if not abrir_url_sefaz(driver, consultascte, nome_thread):
                                    continue
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located(
                                        (By.XPATH, '//*[@id="tipoConsulta"]'))).click()
                                on_consultas = True
                            except TimeoutException:
                                continue
                        sleep(0.2)
                        actions.send_keys(Keys.DOWN).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.ENTER).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.TAB).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.DOWN).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.DOWN).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.TAB).perform()
                        sleep(0.2)
                        actions.send_keys(f'{idDoc}').perform()
                        sleep(0.5)
                        mes = int(execMes)
                        ano = int(execAno)
                        inicio_mes = datetime(ano, mes, 1)
                        if mes == 12:
                            fim_mes = datetime(ano, mes, day=31)
                        else:
                            fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
                        inicio_mes = inicio_mes.strftime("%d/%m/%Y")
                        fim_mes = fim_mes.strftime("%d/%m/%Y")

                        actions.send_keys(Keys.TAB).perform()
                        sleep(3)
                        actions.send_keys(inicio_mes).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.TAB).perform()
                        sleep(0.2)
                        actions.send_keys(fim_mes).perform()
                        sleep(1)
                        campoConsulta = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, '//*[@id="btnConsultar"]')))
                        campoConsulta.click()
                        tempo_carregando = 0
                        continua_carregando = True
            except Exception as e:
                pass
            try:
                msg_erro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, f"SEFAZ-FONT-MensagemErro")))
                if msg_erro:
                    pasta_destino = f"{pastaArquivos}/CTe-Sem Emissor e Tomador.png"
                    if os.path.exists(pasta_destino):
                        os.remove(pasta_destino)
                    driver.save_screenshot(pasta_destino)
                    temregistrosCTE = False

                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Pessoa não possui CTes Emitidos/Tomados.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')

                abrir_url_sefaz(driver, consultascte, nome_thread)
            except Exception as e:
                temregistrosCTE = True
        except Exception as e:
            print('error#5')
            print(e)

    if temregistrosCTE:
        possuiregistrosEmissor = True
        try:
            text_nao_encontrado = 'Não foram encontrados registros para a consulta solicitada.'
            nenhumRegistroEmitidos = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, f"//*[text()='{text_nao_encontrado}']")))
            if nenhumRegistroEmitidos:
                pasta_destino = f"{pastaArquivos}/CTe-Sem-Emissoes.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                possuiregistrosEmissor = False
                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Pessoa não possui emissões de CTe.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
        except Exception as e:
            sleep(0.2)

        if possuiregistrosEmissor:
            try:
                CampoDownload = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="btnGerarExcelConsulta"]')))
                actions.move_to_element(CampoDownload)
                CampoDownload.click()
            except Exception as e:
                print('error#6')
                print(e)

            downloaded = False
            arquivo = fr'{pastaArquivos}\ConsultaCteEmitidoRecebido.xlsx'
            while not downloaded:
                if verify_downloaded(arquivo) is True:
                    downloaded = True
                else:
                    downloaded = False
                sleep(1)
            else:
                arquivoEmissoes = fr'{pastaArquivos}\CT-e Emissor.xlsx'
                arquivos_filtrados = []
                arquivos_xlsx = glob.glob(os.path.join(pastaArquivos, '*.xlsx'))
                for arquivo in arquivos_xlsx:
                    if 'CT-e Emissor' in arquivo:
                        os.remove(arquivo)
                    elif 'CT-e Tomador' in arquivo:
                        os.remove(arquivo)
                    elif 'ConsultaCteEmitidoRecebido' in arquivo:
                        arquivos_filtrados.append(arquivo)

                for arquivo in arquivos_filtrados:
                    os.rename(arquivo, arquivoEmissoes)

                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Arquivos (Excel) CTes emitidos baixado com sucesso.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'SUCESSO',
                               'success-gradient')


def exec_CTE_TOMADOR(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    temregistrosCTE = False
    if not temregistrosCTE:
        try:
            consultascte = 'https://www.sefaz.mt.gov.br/cte/portal/consultaremitidorecebido'
            if not abrir_url_sefaz(driver, consultascte, nome_thread):
                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Erro ao carregar consulta de CTe (Sefaz).',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ERRO',
                               'danger-gradient')
                temregistrosCTE = False
                return

            try:
                msg_erro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, f"SEFAZ-FONT-MensagemErro")))
                if msg_erro:
                    pasta_destino = f"{pastaArquivos}/Erro CTE Sefaz.png"
                    if os.path.exists(pasta_destino):
                        os.remove(pasta_destino)
                    driver.save_screenshot(pasta_destino)

                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Consulta de CTe fora do ar (Sefaz).',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ERRO',
                               'danger-gradient')
                temregistrosCTE = False
            except Exception as e:
                pass

            campoTipo = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                (By.XPATH, '//*[@id="tipoConsulta"]')))

            selectTipo = Select(campoTipo)
            selectTipo.select_by_visible_text('Tomador')

            campoIdentificacao = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                (By.XPATH, '//*[@id="idenTomador"]')))
            selectIdentificacao = Select(campoIdentificacao)
            if tipo_exec == 'PJ':
                selectIdentificacao.select_by_visible_text('CNPJ')

                campoIdentificacaoInput = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="campoCnpjTomador"]')))

                campoIdentificacaoInput.send_keys(f"{idDoc}")
            elif tipo_exec == 'PF':
                selectIdentificacao.select_by_visible_text('CPF')

                campoIdentificacaoInput = WebDriverWait(driver, 5).until(EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="campoCpfTomador"]')))

                campoIdentificacaoInput.send_keys(f"{idDoc}")

            sleep(0.5)
            mes = int(execMes)
            ano = int(execAno)
            inicio_mes = datetime(ano, mes, 1)
            if mes == 12:
                fim_mes = datetime(ano, mes, day=31)
            else:
                fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
            inicio_mes = inicio_mes.strftime("%d/%m/%Y")
            fim_mes = fim_mes.strftime("%d/%m/%Y")

            actions.send_keys(Keys.TAB).perform()
            sleep(3)
            actions.send_keys(inicio_mes).perform()
            sleep(0.2)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.2)
            actions.send_keys(fim_mes).perform()
            sleep(1)
            campoConsulta = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="btnConsultar"]')))
            campoConsulta.click()

            try:
                continua_carregando = True
                tempo_carregando = 0
                while continua_carregando:
                    carregando = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.NAME, 'imgCarregando')))
                    if tempo_carregando < 120:
                        value_carregando = carregando.size['width']
                        if value_carregando > 0:
                            sleep(1)
                            tempo_carregando += 1
                        else:
                            continua_carregando = False
                    elif tempo_carregando >= 120:
                        on_consultas = False
                        while not on_consultas:
                            try:
                                if not abrir_url_sefaz(driver, consultascte, nome_thread):
                                    continue
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located(
                                        (By.XPATH, '//*[@id="tipoConsulta"]'))).click()
                                on_consultas = True
                            except TimeoutException:
                                continue
                        sleep(0.2)
                        actions.send_keys(Keys.DOWN).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.ENTER).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.TAB).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.DOWN).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.DOWN).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.TAB).perform()
                        sleep(0.2)
                        actions.send_keys(f'{idDoc}').perform()
                        sleep(0.5)
                        mes = int(execMes)
                        ano = int(execAno)
                        inicio_mes = datetime(ano, mes, 1)
                        if mes == 12:
                            fim_mes = datetime(ano, mes, day=31)
                        else:
                            fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
                        inicio_mes = inicio_mes.strftime("%d/%m/%Y")
                        fim_mes = fim_mes.strftime("%d/%m/%Y")

                        actions.send_keys(Keys.TAB).perform()
                        sleep(3)
                        actions.send_keys(inicio_mes).perform()
                        sleep(0.2)
                        actions.send_keys(Keys.TAB).perform()
                        sleep(0.2)
                        actions.send_keys(fim_mes).perform()
                        sleep(1)
                        campoConsulta = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, '//*[@id="btnConsultar"]')))
                        campoConsulta.click()
                        tempo_carregando = 0
                        continua_carregando = True
            except Exception as e:
                pass
            try:
                msg_erro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CLASS_NAME, f"SEFAZ-FONT-MensagemErro")))
                if msg_erro:
                    pasta_destino = f"{pastaArquivos}/CTe-Sem Emissor e Tomador.png"
                    if os.path.exists(pasta_destino):
                        os.remove(pasta_destino)
                    driver.save_screenshot(pasta_destino)
                    temregistrosCTE = False

                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Pessoa não possui CTes Emitidos/Tomados.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')

                abrir_url_sefaz(driver, consultascte, nome_thread)
            except Exception as e:
                temregistrosCTE = True
        except Exception as e:
            print('error#5')

    if temregistrosCTE:
        possuiregistrosTomador = True
        try:
            text_nao_encontrado = 'Não foram encontrados registros para a consulta solicitada.'
            nenhumRegistroTomador = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, f"//*[text()='{text_nao_encontrado}']")))
            if nenhumRegistroTomador:
                pasta_destino = f"{pastaArquivos}/CTe-Sem-Tomados.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
            possuiregistrosTomador = False
            driver.execute_script("document.body.style.zoom = '100%'")
            includeLogData(nome_thread,
                           f'CTe - {name_company}',
                           f'Pessoa não possui CTe tomados.',
                           f'{cnpj_cpf}',
                           'SEFAZ',
                           'warning-gradient',
                           'ATENÇÃO',
                           'warning-gradient')

        except Exception as e:
            sleep(0.2)
        if possuiregistrosTomador:
            try:
                CampoDownload = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="btnGerarExcelConsulta"]')))
                CampoDownload.click()

                downloaded = False
                arquivo = fr'{pastaArquivos}\ConsultaCteEmitidoRecebido.xlsx'
                while not downloaded:
                    if verify_downloaded(arquivo) is True:
                        downloaded = True
                    else:
                        downloaded = False
                    sleep(1)
                else:
                    arquivoTomador = fr'{pastaArquivos}\CT-e Tomador.xlsx'
                    if os.path.exists(arquivoTomador):
                        os.remove(arquivoTomador)
                    arquivos_filtrados = []
                    arquivos_xlsx = glob.glob(os.path.join(pastaArquivos, '*.xlsx'))
                    for arquivo in arquivos_xlsx:
                        if 'ConsultaCteEmitidoRecebido' in arquivo:
                            arquivos_filtrados.append(arquivo)

                    for arquivo in arquivos_filtrados:
                        os.rename(arquivo, arquivoTomador)

                    includeLogData(nome_thread,
                                   f'CTe - {name_company}',
                                   f'Arquivos (Excel) CTes tomados baixado com sucesso.',
                                   f'{cnpj_cpf}',
                                   'SEFAZ',
                                   'warning-gradient',
                                   'SUCESSO',
                                   'success-gradient')

            except Exception as e:
                includeLogData(nome_thread,
                               f'CTe - {name_company}',
                               f'Erro ao Consultar CTe Tomado ou lentidão encontrada (Sefaz).',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ERRO',
                               'danger-gradient')


def exec_NFCE(driver, nome_thread, name_company, cnpj_cpf, ie, execMes, execAno, pastaArquivos):
 from selenium.common.exceptions import WebDriverException
 import time

 actions = ActionChains(driver)
 if not ie:
  includeLogData(
   nome_thread,
   f'NFCe - {name_company}',
   f'Pessoa não possui Inscrição Estadual cadastrada para retirar relatório de NFCE.',
   f'{cnpj_cpf}',
   'SEFAZ',
   'warning-gradient',
   'ERRO',
   'danger-gradient'
  )
  return

 # 1. Assumimos por padrão que existem registros até que se prove o contrário
 temregistrosNFC = True
 consultasnfce = 'https://www.sefaz.mt.gov.br/nfce/consultarnfceemitidas'

 try:
  if not abrir_url_sefaz(driver, consultasnfce, nome_thread):
   return

  inscricao_estadual = f'{ie}'
  driver.find_element(By.XPATH, '//*[@id="numrInscEstd"]').send_keys(inscricao_estadual)
  sleep(0.2)

  mes = int(execMes)
  ano = int(execAno)
  inicio_mes = datetime(ano, mes, 1)
  if mes == 12:
   fim_mes = datetime(ano, mes, day=31)
  else:
   fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
  inicio_mes = inicio_mes.strftime("%d/%m/%Y")
  fim_mes = fim_mes.strftime("%d/%m/%Y")

  actions.send_keys(Keys.TAB).perform()
  sleep(3)
  actions.send_keys(inicio_mes).perform()
  sleep(0.5)
  actions.send_keys(Keys.TAB).perform()
  sleep(0.5)
  actions.send_keys(fim_mes).perform()
  sleep(1)

  campoConsulta = WebDriverWait(driver, 10).until(
   EC.presence_of_element_located((By.NAME, "bttnConsultar"))
  )
  campoConsulta.click()
  print("Consulta de NFC-e enviada. Verificando retornos...")
  sleep(2)

  # 2. Verificação de Alerta (Inscrição Inválida)
  try:
   alerta = Alert(driver)
   text_erro = alerta.text
   print(f"Alerta detectado: {text_erro}")
   includeLogData(
    nome_thread,
    f'NFCe - {name_company}',
    f'Alerta SEFAZ: {text_erro}',
    f'{cnpj_cpf}',
    'SEFAZ',
    'warning-gradient',
    'ERRO',
    'danger-gradient'
   )
   alerta.accept()
   temregistrosNFC = False
  except Exception:
   # Sem alertas na tela, prossegue
   pass

  # 3. Verificação de Mensagem de Erro na Página (Se o alerta não pegou)
  if temregistrosNFC:
   try:
    msg_erro_el = WebDriverWait(driver, 4).until(
     EC.presence_of_element_located((By.CLASS_NAME, "SEFAZ-FONT-MensagemErro"))
    )
    msg_erro = (msg_erro_el.get_attribute("textContent") or "").strip()
    print(f"Mensagem de erro SEFAZ detectada na tela: {msg_erro}")

    if 'Nenhuma NFC-e Emitida' in msg_erro or 'Contabilista não representa' in msg_erro:
     pasta_destino = f"{pastaArquivos}/NFCe-Sem Emissoes.png"
     if os.path.exists(pasta_destino):
      os.remove(pasta_destino)
     driver.save_screenshot(pasta_destino)
     temregistrosNFC = False

    includeLogData(
     nome_thread,
     f'NFCe - {name_company}',
     f'{msg_erro}',
     f'{cnpj_cpf}',
     'SEFAZ',
     'warning-gradient',
     'ATENÇÃO',
     'warning-gradient'
    )
    # Retorna para a página de consulta limpa
    abrir_url_sefaz(driver, consultasnfce, nome_thread)

   except Exception:
    # Nenhuma mensagem de erro localizada. Significa que a tabela de registros carregou!
    print("Nenhuma mensagem de erro na tela. Registros de NFC-e localizados!")
    temregistrosNFC = True

 except WebDriverException:
  raise
 except Exception as e:
  print(f"Erro ao processar consulta de NFC-e: {e}")
  temregistrosNFC = False

 # 4. Executa o Download se existirem registros
 if temregistrosNFC:
  try:
   # Limpa qualquer ZIP antigo de NFCe na pasta antes de iniciar
   NomeParcial = 'ConsultaNFCeEmitidas'
   arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
   for arquivo in arquivos_zip:
    if NomeParcial in arquivo:
     os.remove(arquivo)

   # Localiza o botão de exportar para Excel
   CampoDownload = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.XPATH, '//*[@id="bttnExcel"]'))
   )

   # Registra os arquivos que já existem na pasta antes de clicar
   arquivos_antes = set(os.listdir(pastaArquivos))

   # Clica no botão de exportar
   print("Clicando no botão de exportar NFC-e...")
   try:
    click_element_cdp(driver, CampoDownload)
   except Exception:
    CampoDownload.click()

   # Aguarda o download iniciar (surgimento de um arquivo temporário do Chrome)
   print("Aguardando o início do download...")
   download_iniciou = False
   tempo_inicial = time.time()
   timeout_inicio = 12  # Até 12 segundos para o Chrome começar o download

   while (time.time() - tempo_inicial) < timeout_inicio:
    arquivos_agora = set(os.listdir(pastaArquivos))
    novos_arquivos = arquivos_agora - arquivos_antes
    if novos_arquivos:
     for arq in novos_arquivos:
      # Se surgiu o arquivo temporário ou o próprio ZIP
      if arq.endswith('.crdownload') or arq.endswith('.tmp') or 'ConsultaNFCeEmitidas' in arq:
       download_iniciou = True
       print(f"Download iniciado detectado: {arq}")
       break
    if download_iniciou:
     break
    time.sleep(0.5)

   if not download_iniciou:
    raise Exception("O download do ZIP de NFC-e não foi iniciado pelo Chrome no tempo limite.")

   # Aguarda o download terminar (espera o arquivo temporário .crdownload sumir)
   print("Download em andamento... Aguardando conclusão.")
   download_concluido = False
   tempo_inicial = time.time()
   timeout_conclusao = 60  # Até 60 segundos para baixar o ZIP completo

   while (time.time() - tempo_inicial) < timeout_conclusao:
    arquivos_pasta = os.listdir(pastaArquivos)
    # Verifica se ainda existem arquivos temporários ativos
    temporarios = [f for f in arquivos_pasta if f.endswith('.crdownload') or f.endswith('.tmp')]

    if not temporarios:
     # Se não há temporários, confirma se o ZIP final está na pasta
     arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
     for arquivo in arquivos_zip:
      if 'ConsultaNFCeEmitidas' in os.path.basename(arquivo):
       if verify_downloaded(arquivo):
        download_concluido = True
        print("Download concluído com sucesso!")
        break
    if download_concluido:
     break
    time.sleep(1.0)

   if not download_concluido:
    raise Exception("Timeout: O download do ZIP de NFC-e iniciou, mas não terminou a tempo.")

  except WebDriverException:
   raise
  except Exception as e:
   print('error#9')
   print(e)
   includeLogData(
    nome_thread,
    f'NFCe - {name_company}',
    f'Erro ao baixar NFC-e: {e}',
    f'{cnpj_cpf}',
    'SEFAZ',
    'warning-gradient',
    'ERRO',
    'danger-gradient'
   )
   raise

  # Remove planilhas antigas para evitar conflito de nomes
  NomeParcialPlanilha = 'Planilha'
  arquivos_planilha_remover = glob.glob(os.path.join(pastaArquivos, '*.xls'))
  for arquivo in arquivos_planilha_remover:
   if NomeParcialPlanilha in arquivo or 'NFCe Emitidas' in arquivo:
    if os.path.exists(arquivo):
     os.remove(arquivo)

  # Extrai o ZIP recém-baixado
  arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
  for arquivo in arquivos_zip:
   if 'ConsultaNFCeEmitidas' in os.path.basename(arquivo):
    try:
     with zipfile.ZipFile(arquivo, 'r') as nome_zip:
      nome_zip.extractall(path=pastaArquivos, pwd=None)
     print(f"ZIP de NFC-e extraído com sucesso.")
     os.remove(arquivo)  # Deleta o ZIP após extrair
    except Exception as ze:
     print(f"Erro ao extrair ZIP de NFC-e: {ze}")

  # Renomeia a planilha extraída para o nome padrão do sistema
  arquivos_planilha = glob.glob(os.path.join(pastaArquivos, '*.xls'))
  for arquivo_planilha in arquivos_planilha:
   if NomeParcialPlanilha in os.path.basename(arquivo_planilha):
    novo_nome_planilha = fr'{pastaArquivos}\NFCe Emitidas.xls'
    try:
     if os.path.exists(novo_nome_planilha):
      os.remove(novo_nome_planilha)
     os.rename(arquivo_planilha, novo_nome_planilha)
     print(f"Planilha renomeada para: {novo_nome_planilha}")
    except Exception as re:
     print(f"Erro ao renomear planilha de NFC-e: {re}")

  includeLogData(
   nome_thread,
   f'NFCe - {name_company}',
   f'Arquivos (Excel) NFCes Emitidas Baixado com sucesso.',
   f'{cnpj_cpf}',
   'SEFAZ',
   'warning-gradient',
   'SUCESSO',
   'success-gradient'
  )
