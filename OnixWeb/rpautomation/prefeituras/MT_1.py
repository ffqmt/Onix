import shutil
import threading

import PyPDF2
import pandas as pd
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common import NoSuchElementException, ElementNotInteractableException, TimeoutException, NoSuchWindowException
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
import os
import zipfile
import requests
import calendar
import time

from OnixWeb.addons.OnixSender import SendRPAData
# from apps.authentication.models import Companies, ReportsRefreshControl, FilesParameters
# from apps.configs.globals import Globals
from OnixWeb.addons.appscontext import *

from OnixWeb.addons.models import PessoaJuridica, logData, ThreadingCounter, PessoaFisica, AgendamentosRPA, Empresas
from OnixWeb.addons.util import log_message, verify_downloaded, limpar_pasta
from OnixWeb import db
# Configuração para uso da GPU
import torch
import os

# Forçar o uso da GPU
os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # Use a primeira GPU disponível

# Verificar se CUDA está disponível e configurar
if torch.cuda.is_available():
    print(f"GPU detectada: {torch.cuda.get_device_name(0)}")
    print(f"Número de GPUs disponíveis: {torch.cuda.device_count()}")
    # Definir dispositivo padrão para CUDA
    device = torch.device('cuda')
    torch.backends.cudnn.benchmark = True
else:
    print("AVISO: GPU não detectada. Usando CPU.")
    device = torch.device('cpu')

# Configurar EasyOCR para usar GPU se disponível
import easyocr

reader = easyocr.Reader(['pt', 'en'], gpu=torch.cuda.is_available())

root_path = os.path.abspath('')


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
        'enc_taken': bool(Pessoa.pref_enc_tomado),
        'enc_provided': bool(Pessoa.pref_enc_prestado),
        'issqn': bool(Pessoa.pref_guia_issqn),
        'taken': bool(Pessoa.pref_rel_tomado),
        'provided': bool(Pessoa.pref_rel_prestado),
        'nfe_taken': bool(Pessoa.pref_nfe_tomado),
        'nfe_provided': bool(Pessoa.pref_nfe_prestado),
    }

def dadosLoginSefaz(EmpresaExec):
    with app.app_context():
        Empresa = Empresas.query.filter_by(id=2).first()
        if Empresa is None:
            raise ValueError(f"Empresa com ID {EmpresaExec} não encontrada no banco de dados")

        if not Empresa.login_prefeitura or not Empresa.senha_prefeitura:
            raise ValueError(f"Empresa {Empresa.name} não possui dados de login da prefeitura configurados")

    return {'login': Empresa.login_prefeitura, 'senha': Empresa.senha_prefeitura}


def MainExecution_Juridica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
    driver = IniciarDriver()
    '########## REALIZA O LOGIN UNICO SEFAZ ###########'
    logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

    if logado:
        counter = 0
        print(f'Total empresas: {len(dados)} - Thread: {nome_thread}')  # ✅ REMOVIDO dadosAgendamento.id

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

            '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
            anoExec = f'{Ano}'
            if len(str(Mes)) == 1:
                mesExec = f'0{Mes}'
            else:
                mesExec = f'{Mes}'

            '########## VERIFICA PASTA TEMPORARIA ##########'
            nome_empresa = f"{name_company}"
            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "FISCAL PJ", anoExec, mesExec,
                                         "Relatórios")
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['enc_taken']:
                exec_ENC_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
            if listaParametros['enc_provided']:
                exec_ENC_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)

            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

            if listaParametros['issqn']:
                exec_GUIAISSQN(driver=driver,
                               nome_thread=nome_thread,
                               name_company=name_company,
                               cnpj_cpf=username,
                               idDoc=username,
                               execMes=mesExec,
                               execAno=anoExec,
                               pastaArquivos=pastaArquivos)
            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver=driver,
                                  nome_thread=nome_thread,
                                  name_company=name_company,
                                  cnpj_cpf=username,
                                  idDoc=username,
                                  execMes=mesExec,
                                  execAno=anoExec,
                                  pastaArquivos=pastaArquivos)
                '''exec_XML_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)'''
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver=driver,
                                    nome_thread=nome_thread,
                                    name_company=name_company,
                                    cnpj_cpf=username,
                                    idDoc=username,
                                    execMes=mesExec,
                                    execAno=anoExec,
                                    pastaArquivos=pastaArquivos)
                '''exec_XML_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)'''

            sleep(20)
            limpar_pasta(pastaArquivos)

            # ✅ MOVER TUDO PARA DENTRO DO LOOP
            counter += 1
            print(f'Finalizado: {counter}/{len(dados)} - Thread: {nome_thread} - Pessoa: ({id_company}) {name_company}')

            includeLogData(nome_thread,
                           f'PROCESSOS - {pessoa["name"]}',
                           'Processos finalizados para a empresa...',
                           'BOT',
                           'BOT',
                           'primary-gradient',
                           'SUCESSO',
                           'success-gradient')
            setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
            percentilInicial = percentilInicial + percentilPorPessoa

        '########## FINALIZA O DRIVER ##########'
        driver.close()
    else:
        # Ver comentário nas outras 3 variantes (Padrao/Expecifico) --
        # sem isto o Chrome fica pendurado e trava o perfil persistente
        # pra qualquer execução seguinte.
        driver.quit()

    '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
    try:
        shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Arquivo gerado e disponível!',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, 100)
        print(f'A pasta foi zipada com sucesso: {caminho_pasta}.zip')
    except Exception as e:
        print(f"Ocorreu um erro ao zipar a pasta: {e}")
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger-gradient')


def MainExecution_Juridica_Padrao(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
    driver = IniciarDriver()
    '########## REALIZA O LOGIN UNICO PREFEITURA ###########'
    logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

    if logado:

        for pessoa in dados:
            counter += 1
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

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['enc_taken']:
                exec_ENC_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
            elif listaParametros['enc_provided']:
                exec_ENC_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
            elif listaParametros['taken']:
                exec_PDF_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)

            elif listaParametros['provided']:
                exec_PDF_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

            elif listaParametros['issqn']:
                exec_GUIAISSQN(driver=driver,
                               nome_thread=nome_thread,
                               name_company=name_company,
                               cnpj_cpf=username,
                               idDoc=username,
                               execMes=mesExec,
                               execAno=anoExec,
                               pastaArquivos=pastaArquivos)
            elif listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver=driver,
                                  nome_thread=nome_thread,
                                  name_company=name_company,
                                  cnpj_cpf=username,
                                  idDoc=username,
                                  execMes=mesExec,
                                  execAno=anoExec,
                                  pastaArquivos=pastaArquivos)
                exec_XML_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
            elif listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver=driver,
                                    nome_thread=nome_thread,
                                    name_company=name_company,
                                    cnpj_cpf=username,
                                    idDoc=username,
                                    execMes=mesExec,
                                    execAno=anoExec,
                                    pastaArquivos=pastaArquivos)
                exec_XML_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

            sleep(10)
            limpar_pasta(pastaArquivos)
            counter += 1  # ✅ ADICIONAR NO FINAL DO LOOP
            print(
                f'Finalizado: {counter}/{len(dados)} - AgendamentoID {dadosAgendamento.id} - Thread: fetchlog-{nome_thread} - Pessoa: ({id_company}) {name_company}')  # ✅ ADICIONAR

        '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Processos finalizados para a empresa...',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
        percentilInicial = percentilInicial + percentilPorPessoa

        driver.close()
    else:
        # Login falhou (ex: sessão do certificado expirada) -- sem isto o
        # Chrome/chromedriver nunca fecha, trava o perfil persistente e
        # QUALQUER execução seguinte (manual ou agendada) falha até
        # alguém matar o processo zumbi manualmente. Achado ao vivo em
        # 01/09/2026 tentando reproduzir esse cenário de propósito.
        driver.quit()

    '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
    try:
        shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Arquivo gerado e disponível!',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, 100)
        print(f'A pasta foi zipada com sucesso: {caminho_pasta}.zip')
    except Exception as e:
        print(f"Ocorreu um erro ao zipar a pasta: {e}")
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger-gradient')


def MainExecution_Fisica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
    driver = IniciarDriver()
    '########## REALIZA O LOGIN UNICO PREFEITURA DE PVA ###########'
    logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

    if logado:

        for pessoa in dados:
            includeLogData(nome_thread,
                           f'PROCESSOS - {pessoa["name"]}',
                           'Iniciando processos para a Pessoa Física...',
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
            if listaParametros['enc_taken']:
                exec_ENC_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
            if listaParametros['enc_provided']:
                exec_ENC_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
                exec_XML_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                exec_XML_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
            if listaParametros['issqn']:
                exec_GUIAISSQN(driver=driver,
                               nome_thread=nome_thread,
                               name_company=name_company,
                               cnpj_cpf=username,
                               idDoc=username,
                               execMes=mesExec,
                               execAno=anoExec,
                               pastaArquivos=pastaArquivos)
            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver=driver,
                                  nome_thread=nome_thread,
                                  name_company=name_company,
                                  cnpj_cpf=username,
                                  idDoc=username,
                                  execMes=mesExec,
                                  execAno=anoExec,
                                  pastaArquivos=pastaArquivos)
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver=driver,
                                    nome_thread=nome_thread,
                                    name_company=name_company,
                                    cnpj_cpf=username,
                                    idDoc=username,
                                    execMes=mesExec,
                                    execAno=anoExec,
                                    pastaArquivos=pastaArquivos)

            sleep(20)
            limpar_pasta(pastaArquivos)

        '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Processos finalizados para a empresa...',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
        percentilInicial = percentilInicial + percentilPorPessoa

        driver.close()
    else:
        # Login falhou (ex: sessão do certificado expirada) -- sem isto o
        # Chrome/chromedriver nunca fecha, trava o perfil persistente e
        # QUALQUER execução seguinte (manual ou agendada) falha até
        # alguém matar o processo zumbi manualmente. Achado ao vivo em
        # 01/09/2026 tentando reproduzir esse cenário de propósito.
        driver.quit()

    '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
    try:
        shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Arquivo gerado e disponível!',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, 100)
        print(f'A pasta foi zipada com sucesso: {caminho_pasta}.zip')
    except Exception as e:
        print(f"Ocorreu um erro ao zipar a pasta: {e}")
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger-gradient')


def MainExecution_Fisica_Padrao(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    dadosLogin = dadosLoginSefaz(EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
    driver = IniciarDriver()
    '########## REALIZA O LOGIN UNICO SEFAZ ###########'
    logado = exec_LOGIN(driver, nome_thread, dadosLogin['login'], dadosLogin['senha'])

    if logado:

        for pessoa in dados:
            includeLogData(nome_thread,
                           f'PROCESSOS - {pessoa["name"]}',
                           'Iniciando processos para a Pessoa Física...',
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
            nome_empresa = f"{name_company} - {username}"
            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'

            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
                exec_XML_TOMADOS(driver=driver,
                                 nome_thread=nome_thread,
                                 name_company=name_company,
                                 cnpj_cpf=username,
                                 idDoc=username,
                                 execMes=mesExec,
                                 execAno=anoExec,
                                 pastaArquivos=pastaArquivos)
            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                exec_XML_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver=driver,
                                  nome_thread=nome_thread,
                                  name_company=name_company,
                                  cnpj_cpf=username,
                                  idDoc=username,
                                  execMes=mesExec,
                                  execAno=anoExec,
                                  pastaArquivos=pastaArquivos)
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver=driver,
                                    nome_thread=nome_thread,
                                    name_company=name_company,
                                    cnpj_cpf=username,
                                    idDoc=username,
                                    execMes=mesExec,
                                    execAno=anoExec,
                                    pastaArquivos=pastaArquivos)

            sleep(20)
            limpar_pasta(pastaArquivos)

        '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Processos finalizados para a empresa...',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, percentilInicial + percentilPorPessoa)
        percentilInicial = percentilInicial + percentilPorPessoa

        driver.close()
    else:
        # Login falhou (ex: sessão do certificado expirada) -- sem isto o
        # Chrome/chromedriver nunca fecha, trava o perfil persistente e
        # QUALQUER execução seguinte (manual ou agendada) falha até
        # alguém matar o processo zumbi manualmente. Achado ao vivo em
        # 01/09/2026 tentando reproduzir esse cenário de propósito.
        driver.quit()

    '########## ZIPA OS ARQUIVOS PARA DISPONIBILIZAR LINK E REMOVE A PASTA ######'
    try:
        shutil.make_archive(caminho_pasta, 'zip', caminho_pasta)
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Arquivo gerado e disponível!',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')
        setPercentilProcesso(nome_thread, 100)
        print(f'A pasta foi zipada com sucesso: {caminho_pasta}.zip')
    except Exception as e:
        print(f"Ocorreu um erro ao zipar a pasta: {e}")
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger-gradient')


def MainExecution_Agendamentos(idAgendamento, listaParametros, EmpresaExec, idCidade=1):
    with app.app_context():
        dadosAgendamento = AgendamentosRPA.query.filter_by(id=idAgendamento).first()
        dadosAgendamento.status = 'Em Execução'
        dadosLogin = dadosLoginSefaz(EmpresaExec)
        db.session.commit()

        if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
            DPbd = PessoaJuridica.query.filter_by(id_city=idCidade, active=True, active_mensal=True,
                                                  id_empresa=dadosAgendamento.id_empresa).all()
        elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
            DPbd = PessoaFisica.query.filter_by(id_city=idCidade, active=True, active_mensal=True,
                                                id_empresa=dadosAgendamento.id_empresa).all()

        ParametrosAgendamento = []
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
        percentilPorPessoa = int(percentilProcesso / listaLen)
        percentilInicial = 5
        setPercentilProcesso(nome_thread, percentilInicial)

        '########## INICIA O DRIVER E CONFIGURA PARA EXECUÇÃO UNICA ##########'
        driver = IniciarDriver()
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
                    listaParametros = checkParamPadrao('PJ', id_company)
                elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                    listaParametros = checkParamPadrao('PF', id_company)

                '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
                anoExec = f'{AnoExecucao}'
                if len(str(MesExecucao)) == 1:
                    mesExec = f'0{MesExecucao}'
                else:
                    mesExec = f'{MesExecucao}'

                #nome_empresa = ''
                '########## VERIFICA PASTA TEMPORARIA ##########'
                if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
                    nome_empresa = f"{name_company}"
                elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                    nome_empresa = f"{name_company}"

                # Define o caminho base com ou sem pasta "rural" dependendo do tipo de pessoa
                if dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                    pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "Rural", anoExec, mesExec,
                                                 "Relatórios")
                else:
                    pastaArquivos = os.path.join(caminho_pasta, nome_empresa, "FISCAL PJ", anoExec, mesExec, "Relatórios")

                # Cria todas as pastas necessárias
                try:
                    os.makedirs(pastaArquivos, exist_ok=True)
                    print(f"✅ Estrutura de pastas criada: {pastaArquivos}")
                except Exception as e:
                    print(f"❌ Erro ao criar estrutura de pastas: {str(e)}")
                    raise

                driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                       {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})



                '######### EXECUTA ESCOLHAS APOS LOGADO ########'
                if listaParametros['enc_taken']:
                    exec_ENC_TOMADOS( driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['enc_provided']:
                    exec_ENC_PRESTADOS( driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['taken']:
                    exec_PDF_TOMADOS( driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

                if listaParametros['provided']:
                    exec_PDF_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)

                if listaParametros['issqn']:
                    exec_GUIAISSQN(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['nfe_taken']:
                    exec_NFSE_TOMADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                    exec_XML_TOMADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                if listaParametros['nfe_provided']:
                    exec_NFSE_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)
                    exec_XML_PRESTADOS(driver=driver,
                                   nome_thread=nome_thread,
                                   name_company=name_company,
                                   cnpj_cpf=username,
                                   idDoc=username,
                                   execMes=mesExec,
                                   execAno=anoExec,
                                   pastaArquivos=pastaArquivos)


                sleep(10)
                limpar_pasta(pastaArquivos)

                '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

            includeLogData(nome_thread,
                           f'PROCESSOS - {pessoa["name"]}',
                           'Processos finalizados para a empresa...',
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
                shutil.make_archive(caminhoZip, 'zip', caminhoZip)
                includeLogData(nome_thread,
                               f'ARQUIVO ZIP EMPRESA',
                               'Arquivo gerado e disponível!',
                               'BOT',
                               'BOT',
                               'primary-gradient',
                               'SUCESSO',
                               'success-gradient')
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
                    SendRPAData(dadosAgendamento.id, zipData, receiver_ip, receiver_ip_secondary, receiver_port,
                                pathEnvio)

                    print('Envio Finalizado!')

            elif tipo_envio == 'zip':
                '### EXTRAI ARQUIVOS NO SERVIDOR BASE TIPO PESSOA'
                pathEnvio = os.path.join(dadosAgendamento.path_receiver, nome_empresa)
                zipData = os.path.join(fr"{caminhoZip}.zip")
                with zipfile.ZipFile(zipData, 'r') as zip_ref:
                    zip_ref.extractall(pathEnvio)

        # Esta função (execução agendada) nunca fechava o driver, nem no
        # sucesso nem na falha -- diferente das outras 4 variantes
        # (Padrao/Expecifico), que ao menos fechavam no sucesso. Pra um
        # agendamento que roda sozinho, isso significa QUALQUER execução
        # -- não só as que falham no login -- deixa um Chrome pendurado
        # segurando o perfil persistente, travando o próximo agendamento.
        # Achado ao vivo em 01/09/2026 junto com o mesmo bug nas outras 4.
        try:
            driver.quit()
        except Exception:
            pass

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


def dadosPessoasPF(listaPessoas, EmpresaExec):
    with app.app_context():
        dadospessoas = []

        for id_pessoa in listaPessoas:
            DPbd = PessoaFisica.query.options(joinedload(PessoaFisica.city)).filter_by(id_city=1,
                                                                                       id_empresa=EmpresaExec,
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
            DPbd = PessoaJuridica.query.options(joinedload(PessoaJuridica.city)).filter_by(id_city=1,
                                                                                           id_empresa=EmpresaExec,
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


# Portal trocou em 08/2026: era cidadaoonline.primaveradoleste.mt.gov.br (SPA
# Angular), agora é o ISSWeb da Fiorilli (JSF/PrimeFaces). Login por
# usuário/senha não funciona mais -- o portal exige certificado digital
# mesmo (confirmado ao vivo), via um diálogo *dentro da página* controlado
# pela extensão "Fiorilli Web Extension". Essa extensão detecta clique de
# script vs clique real de propósito (anti-automação), então:
#   1. O perfil do Chrome precisa ser FIXO e persistente (não um novo por
#      execução como antes) -- a extensão só existe nesse perfil se alguém
#      a instalar manualmente nele uma vez.
#   2. O login com certificado não dá pra automatizar -- é feito manualmente
#      por um humano com acesso ao certificado, rodando este arquivo com
#      `python -m OnixWeb.rpautomation.prefeituras.MT_1 --login-manual`
#      (headless=False, o script para e espera Enter). A sessão fica salva
#      no perfil e é reaproveitada pelas execuções automáticas seguintes,
#      até expirar -- exec_LOGIN() só CONFERE se a sessão ainda vale, não
#      tenta logar sozinho.
PERFIL_CHROME_PERSISTENTE = os.path.join(
    root_path, r"OnixWeb\rpautomation\dependencias\chrome_profile_pva_persistente"
)


def IniciarDriver(headless: bool = False):
 # Default False = mesmo comportamento de antes (janela sempre visivel) --
 # nao sabemos se o modo headless novo do Chrome quebra a extensao
 # Fiorilli Web Extension em algum passo alem do login (que ja e manual e
 # roda com headless=False explicito via --login-manual). Mudar esse
 # default pra True em producao e uma escolha separada, nao decidida aqui.
 import os

 caminho_driver = os.path.join(
  root_path,
  r"OnixWeb\rpautomation\dependencias\chromedriver\chromedriver.exe"
 )

 print(f"🔧 ChromeDriver usado: {caminho_driver}")
 print(f"🔧 ChromeDriver existe? {os.path.exists(caminho_driver)}")

 chrome_options = Options()

 os.makedirs(PERFIL_CHROME_PERSISTENTE, exist_ok=True)
 chrome_options.add_argument(f"--user-data-dir={PERFIL_CHROME_PERSISTENTE}")
 if headless:
     chrome_options.add_argument("--headless=new")
 chrome_options.add_argument("--window-size=1080,900")
 chrome_options.add_argument("--start-maximized")
 chrome_options.add_argument("--disable-notifications")
 chrome_options.add_argument("--disable-popup-blocking")
 chrome_options.add_argument("--remote-debugging-port=0")

 # NÃO usar por enquanto:
 # chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
 # chrome_options.add_experimental_option("useAutomationExtension", False)

 prefs = {
  "download.extensions_to_open": "",
  "plugins.always_open_pdf_externally": True,
  "credentials_enable_service": False,
  "download.prompt_for_download": False,
  "download.directory_upgrade": True,
  "profile.password_manager_enabled": False,
  "profile.default_content_setting_values.notifications": 2
 }

 chrome_options.add_experimental_option("prefs", prefs)

 service = Service(
  caminho_driver,
  log_output=os.path.join(root_path, "chromedriver_verbose.log")
 )
 service.service_args = ["--verbose"]

 print("🚀 Abrindo Chrome...")
 driver = webdriver.Chrome(service=service, options=chrome_options)
 print("✅ Chrome abriu e sessão Selenium foi criada.")

 driver.set_page_load_timeout(60)
 driver.set_script_timeout(60)

 return driver


def esperar_e_renomear_arquivo(pasta, novo_nome, timeout=30, intervalo=30):
    """
    Espera que um arquivo PDF esteja disponível na pasta e o renomeia,
    excluindo arquivos específicos da lista de exclusão.

    :param pasta: Caminho da pasta onde o arquivo será baixado.
    :param novo_nome: Novo nome para o arquivo baixado (incluindo extensão).
    :param timeout: Tempo máximo (em segundos) para aguardar o download.
    :param intervalo: Intervalo de tempo (em segundos) entre verificações.
    :return: Caminho completo do arquivo renomeado.
    """
    tempo_inicial = time.time()

    # Extensao alvo derivada de novo_nome -- ate 01/09/2026 essa funcao so
    # era chamada com nomes .pdf (hardcoded abaixo), o que quebrava
    # silenciosamente pra downloads .zip/.xml (Gerar XML do portal novo).
    extensao_alvo = os.path.splitext(novo_nome)[1] or ".pdf"

    # Lista de arquivos que devem ser ignorados (nomes finais ja
    # renomeados de rodadas anteriores, so relevante pra .pdf ate agora)
    arquivos_excluidos = [
        "NFS-e - Tomados.pdf",
        "NOTAS - Tomados.pdf",
        "NFS-e - Prestados.pdf",
        "NOTAS - Prestados.pdf",
        "DEC. SEM MOVIMENTO - PRESTADOS.pdf",
        "DEC. SEM MOVIMENTO - TOMADOS.pdf",
        "GUIA ISSQN.pdf",
        "NOTAS - P. Canceladas.pdf"

    ]

    while True:
        # Lista os arquivos na pasta
        arquivos = os.listdir(pasta)
        print(f"Arquivos encontrados: {arquivos}")

        # Verifica se ha algum arquivo do tipo esperado disponivel (excluindo os da lista)
        for arquivo in arquivos:
            if arquivo.endswith(extensao_alvo) and arquivo not in arquivos_excluidos:
                caminho_antigo = os.path.join(pasta, arquivo)
                caminho_novo = os.path.join(pasta, novo_nome)

                # Verifica se o arquivo de destino já existe
                if os.path.exists(caminho_novo):
                    print(f"Arquivo de destino '{novo_nome}' já existe. Pulando renomeação.")
                    continue

                try:
                    os.rename(caminho_antigo, caminho_novo)
                    print(f"Arquivo renomeado de '{arquivo}' para: '{novo_nome}'")
                    return caminho_novo
                except OSError as e:
                    print(f"Erro ao renomear arquivo '{arquivo}': {e}")
                    continue

        # Verifica se o tempo limite foi atingido
        if time.time() - tempo_inicial > timeout:
            raise Exception(
                f"Nenhum arquivo PDF válido foi encontrado na pasta dentro do tempo limite de {timeout} segundos.")

        # Aguarda o intervalo antes de verificar novamente
        time.sleep(intervalo)

# Portal novo (ISSWeb/Fiorilli, desde 08/2026) -- mapeado ao vivo em
# 01/09/2026 contra uma sessão autenticada de verdade (certificado da
# Contaudi). Ver comentário em PERFIL_CHROME_PERSISTENTE acima: login por
# certificado não é automatizável, exec_LOGIN só confere se a sessão do
# perfil persistente ainda vale.
URL_LOGIN_PVA = "https://iss.primaveradoleste.mt.gov.br/issweb/paginas/login"
URL_SELECIONAR_CONTRIBUINTE_PVA = "https://iss.primaveradoleste.mt.gov.br/issweb/paginas/admin/selecionarContribuinte"
URL_NOTAS_PRESTADAS_PVA = "https://iss.primaveradoleste.mt.gov.br/issweb/paginas/admin/notafiscal/pesquisarNF"
URL_NOTAS_TOMADAS_PVA = "https://iss.primaveradoleste.mt.gov.br/issweb/paginas/admin/tomador/minhasnotas"


def exec_LOGIN(driver, nome_thread, login_prefeitura, senha_prefeitura):
    """Confere se a sessão do perfil persistente (PERFIL_CHROME_PERSISTENTE)
    ainda está logada -- NÃO tenta logar sozinha. O portal exige
    certificado digital (usuário/senha foi testado ao vivo e recusado:
    "Usuário e/ou Senha inválidos" mesmo com credencial certa) via um
    diálogo controlado pela extensão "Fiorilli Web Extension", que detecta
    clique de script e recusa -- automatizar esse clique não é algo que
    fazemos aqui (mesma categoria de "instalar/autorizar coisa no sistema"
    que fica fora do que o bot executa sozinho).

    Login real é manual: rode
    `python -m OnixWeb.rpautomation.prefeituras.MT_1 --login-manual` numa
    janela visível, clique o certificado você mesmo, a sessão fica salva
    no perfil persistente e essa função passa a devolver True até a sessão
    expirar de novo.

    login_prefeitura/senha_prefeitura ficam nos parâmetros só por
    compatibilidade com as chamadas existentes (MainExecution_*) -- não
    são mais usados.
    """
    includeLogData(nome_thread,
                   f'LOGIN - CONTABILISTA',
                   f'Verificando sessão do certificado digital...',
                   f'BOT',
                   'PREFEITURA DE PRIMAVERA DO LESTE',
                   'warning-gradient',
                   'ATENÇÃO',
                   'warning-gradient')

    logado = False
    try:
        driver.get(URL_LOGIN_PVA)
        # JSF redireciona pra fora de /paginas/login em qualquer sessão
        # válida -- mais robusto que apostar numa URL de destino
        # específica.
        WebDriverWait(driver, 10).until(lambda d: "/paginas/login" not in d.current_url)
        logado = "/paginas/login" not in driver.current_url
    except TimeoutException:
        logado = False
    except Exception as e:
        print(f"Erro ao verificar sessão: {e}")
        logado = False

    if logado:
        includeLogData(nome_thread,
                    'LOGIN - CONTABILISTA',
                    'Sessão do certificado digital válida.',
                    'BOT',
                    'PREFEITURA DE PRIMAVERA DO LESTE',
                    'warning-gradient',
                    'SUCESSO',
                    'success-gradient')
        print('Sessão PREFEITURA válida (login manual anterior ainda ativo)')
    else:
        includeLogData(nome_thread,
                    'LOGIN - CONTABILISTA',
                    'Sessão expirada ou nunca aberta -- alguém precisa logar manualmente com '
                    'certificado digital (python -m OnixWeb.rpautomation.prefeituras.MT_1 --login-manual).',
                    'BOT',
                    'PREFEITURA DE PRIMAVERA DO LESTE',
                    'warning-gradient',
                    'ERRO',
                    'danger-gradient')
        print('Sessão PREFEITURA expirada -- precisa de login manual com certificado')

    return logado


def _selecionar_contribuinte(driver, nome_thread, cnpj_cpf):
    """Login na Contaudi é de contador multi-empresa (diferente do portal
    antigo, que logava direto numa empresa) -- toda consulta precisa
    rodar no contexto do contribuinte certo, selecionado por CNPJ/CPF
    nesta tela antes. Ids reais vistos ao vivo em 01/09/2026: campo
    'form:itCpfCnpj', botão 'form:btnDefault', resultado numa tabela
    'form:listaContribuintes' com um botão de seleção por linha (assume
    1a linha porque a busca é por CNPJ/CPF exato)."""
    try:
        driver.get(URL_SELECIONAR_CONTRIBUINTE_PVA)

        campo_cnpj = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[id$=":itCpfCnpj"]'))
        )
        campo_cnpj.clear()
        campo_cnpj.send_keys(cnpj_cpf)

        botao_pesquisar = driver.find_element(By.CSS_SELECTOR, 'button[id$=":btnDefault"]')
        botao_pesquisar.click()

        # O id "listaContribuintes" fica numa <div> (o wrapper PrimeFaces
        # do datatable), não numa <table> -- confirmado via diagnóstico
        # (_diagnostico_pva/) em 01/09/2026 depois do seletor "table[...]"
        # nunca casar com nada e estourar timeout. Sem prefixo de tag,
        # casa com qualquer elemento.
        botao_selecionar = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '[id$=":listaContribuintes"] tbody tr:first-child button'))
        )
        botao_selecionar.click()
        sleep(1.5)  # AJAX de troca de contexto do contribuinte
        return True
    except TimeoutException:
        print(f"Contribuinte não encontrado para CNPJ/CPF {cnpj_cpf}")
        _salvar_diagnostico(driver, f"selecionar_contribuinte_{cnpj_cpf}")
        includeLogData(nome_thread,
                       'SELECIONAR CONTRIBUINTE',
                       f'Nenhum contribuinte encontrado para {cnpj_cpf} no portal da prefeitura.',
                       cnpj_cpf,
                       'PREFEITURA DE PRIMAVERA DO LESTE',
                       'warning-gradient',
                       'ERRO',
                       'danger-gradient')
        return False
    except Exception as e:
        print(f"Erro ao selecionar contribuinte {cnpj_cpf}: {e}")
        _salvar_diagnostico(driver, f"selecionar_contribuinte_erro_{cnpj_cpf}")
        return False


def _salvar_diagnostico(driver, prefixo):
    """Screenshot + HTML da página no momento da falha -- pra diagnosticar
    sem precisar de acesso ao vivo de novo (seletor mudou? elemento tem
    outro id? nunca apareceu resultado?). Salva em
    OnixWeb/rpautomation/dependencias/_diagnostico_pva/, nunca derruba a
    execução por conta própria (best-effort)."""
    try:
        pasta = os.path.join(root_path, r"OnixWeb\rpautomation\dependencias\_diagnostico_pva")
        os.makedirs(pasta, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        driver.save_screenshot(os.path.join(pasta, f"{prefixo}_{ts}.png"))
        with open(os.path.join(pasta, f"{prefixo}_{ts}.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        with open(os.path.join(pasta, f"{prefixo}_{ts}_url.txt"), "w", encoding="utf-8") as f:
            f.write(driver.current_url)
        print(f"Diagnóstico salvo em {pasta} (prefixo {prefixo}_{ts})")
    except Exception as e:
        print(f"Não consegui salvar diagnóstico: {e}")


def _buscar_e_exportar_notas(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos,
                              url_lista, nome_arquivo_pdf, nome_arquivo_xml, tipo_log):
    """Compartilhado pelas 4 funções de notas (tomadas/prestadas x
    PDF/XML) -- mesmo padrão de tela no portal novo (intervalo de data +
    pesquisar + botões que exportam TODO o resultado filtrado de uma vez,
    sem precisar marcar nota por nota como no portal antigo): campos
    'dtInicio_input'/'dtFim_input', pesquisar ('cbPesquisar' na tela de
    prestadas, 'btnDefault' na de tomadas -- por isso tentamos os dois),
    exportar ('cbImprimirButton'/'cbGerarXml' em prestadas,
    'cbImprimirList'/'cbGerarXmlList' em tomadas -- por isso tentamos
    ambos os sufixos). Presume que _selecionar_contribuinte já rodou
    nesta mesma navegação."""
    mes = int(execMes)
    ano = int(execAno)
    if mes == 12:
        ultimo_dia = 31
    else:
        ultimo_dia = (datetime(ano, mes + 1, 1) - timedelta(days=1)).day
    data_inicio = f"01/{mes:02d}/{ano}"
    data_fim = f"{ultimo_dia:02d}/{mes:02d}/{ano}"

    try:
        driver.get(url_lista)

        campo_inicio = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[id$=":dtInicio_input"]'))
        )
        campo_inicio.clear()
        campo_inicio.send_keys(data_inicio)

        campo_fim = driver.find_element(By.CSS_SELECTOR, 'input[id$=":dtFim_input"]')
        campo_fim.clear()
        campo_fim.send_keys(data_fim)
        campo_fim.send_keys(Keys.TAB)

        try:
            botao_pesquisar = driver.find_element(By.CSS_SELECTOR, 'button[id$=":cbPesquisar"]')
        except NoSuchElementException:
            botao_pesquisar = driver.find_element(By.CSS_SELECTOR, 'button[id$=":btnDefault"]')
        botao_pesquisar.click()

        sleep(2.5)  # AJAX da busca assentar antes de procurar os botões de exportação

        driver.execute_cdp_cmd('Page.setDownloadBehavior',
                               {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

        arquivos_baixados = []

        if nome_arquivo_pdf:
            try:
                try:
                    botao_pdf = driver.find_element(By.CSS_SELECTOR, 'button[id$=":cbImprimirButton"]')
                except NoSuchElementException:
                    botao_pdf = driver.find_element(By.CSS_SELECTOR, 'button[id$=":cbImprimirList"]')
                # Clique nativo esbarrava numa "statusBar" fixa cobrindo o
                # botão perto do rodapé (confirmado ao vivo, "element click
                # intercepted") -- clique via JS ignora sobreposição visual,
                # mesmo truque que MT_1.py já usava em outros lugares (ex:
                # radio_button de GUIAISSQN) antes desta correção.
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_pdf)
                driver.execute_script("arguments[0].click();", botao_pdf)
                caminho = esperar_e_renomear_arquivo(pastaArquivos, nome_arquivo_pdf, intervalo=6)
                if caminho and os.path.exists(caminho):
                    arquivos_baixados.append(caminho)
            except NoSuchElementException:
                print(f"Botão 'Gerar PDF' não encontrado ({tipo_log}) -- sem resultado nesse período?")
            except Exception as e:
                # Nao deixa uma falha aqui (ex: timeout esperando o
                # download) derrubar a tentativa de XML logo abaixo.
                print(f"Falha ao baixar/renomear PDF ({tipo_log}): {e}")

        if nome_arquivo_xml:
            # Confirmado ao vivo em 01/09/2026: 'Gerar XML' baixa um .xml
            # unico (nome real do portal: LoteNFSe_DD_MM_AAAA.xml), nao um
            # .zip -- o botao 'Gerar ZIP' e outro, separado, nao usado aqui.
            try:
                try:
                    botao_xml = driver.find_element(By.CSS_SELECTOR, 'button[id$=":cbGerarXml"]')
                except NoSuchElementException:
                    botao_xml = driver.find_element(By.CSS_SELECTOR, 'button[id$=":cbGerarXmlList"]')
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_xml)
                driver.execute_script("arguments[0].click();", botao_xml)
                caminho = esperar_e_renomear_arquivo(pastaArquivos, nome_arquivo_xml, intervalo=10)
                if caminho and os.path.exists(caminho):
                    arquivos_baixados.append(caminho)
            except NoSuchElementException:
                print(f"Botão 'Gerar XML' não encontrado ({tipo_log}) -- sem resultado nesse período?")
            except Exception as e:
                print(f"Falha ao baixar/renomear XML ({tipo_log}): {e} -- extensão esperada pode estar errada, ver comentário acima")

        sucesso = len(arquivos_baixados) > 0
        includeLogData(nome_thread,
                       f'{tipo_log} - {name_company}',
                       f'{len(arquivos_baixados)} arquivo(s) baixado(s).' if sucesso else 'Nenhum arquivo baixado (sem notas no período?).',
                       cnpj_cpf,
                       tipo_log,
                       'info-gradient',
                       'SUCESSO' if sucesso else 'ATENÇÃO',
                       'success-gradient' if sucesso else 'warning-gradient')
        return sucesso

    except Exception as e:
        print(f"Erro geral em _buscar_e_exportar_notas ({tipo_log}): {e}")
        includeLogData(nome_thread,
                       f'{tipo_log} - {name_company}',
                       f'Erro: {e}',
                       cnpj_cpf,
                       tipo_log,
                       'info-gradient',
                       'ERRO',
                       'danger-gradient')
        return False


def exec_PDF_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    if not _selecionar_contribuinte(driver, nome_thread, cnpj_cpf):
        return
    _buscar_e_exportar_notas(
        driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos,
        url_lista=URL_NOTAS_TOMADAS_PVA,
        nome_arquivo_pdf="NFS-e - Tomados.pdf",
        nome_arquivo_xml=None,
        tipo_log="TOMADOS",
    )


'''
def exec_XML_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    includeLogData(nome_thread,
                   f'NFSE - {name_company}',
                   f'Iniciando processo de download de NFSe de serviços Tomados.',
                   f'{cnpj_cpf}',
                   'TOMADOS',
                   'info-gradient',
                   'SUCESSO',
                   'success-gradient')

    pasta_xml_tomados = os.path.join(pastaArquivos, 'XML - Tomados')

    # Crie a pasta se não existir
    if not os.path.exists(pasta_xml_tomados):
        os.makedirs(pasta_xml_tomados)
        print(f"Pasta criada: {pasta_xml_tomados}")


    try:
        xml_prestadas = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/notasubstitutiva'
        driver.get(f'{xml_prestadas}')

        ng_select = WebDriverWait(driver, 9).until(
            EC.presence_of_element_located((By.XPATH, "//ng-select"))
        )
        ng_select.click()

        # Certifique-se de que idDoc está definido antes de usar

        for char in f'{cnpj_cpf}':
            # Espera até que o campo de entrada esteja presente
            campoEntrada = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
            )

            # Envia o texto desejado para o campo de entrada
            campoEntrada.send_keys(cnpj_cpf)  # Envia a string completa

            # Espera que a lista de resultados apareça
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()  # Clica na primeira opção

            # Preencher o campo de data
            campoData = WebDriverWait(driver, 1).until(
                EC.presence_of_element_located((By.XPATH, '//input[@formcontrolname="competencia"]'))
            )
            campoData.click()  # Clica no campo de data
            campoData.clear()  # Limpa o campo antes de digitar
            campoData.send_keys(f"{mes}/{ano}")  # Digita a data no formato desejado
            campoData.send_keys(Keys.TAB)

            sleep(2)

            # Selecionar a quantidade de itens por página
            selectQuantidade = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, 'pagination'))  # Ajuste o nome conforme necessário
            )
            select = Select(selectQuantidade)
            select.select_by_visible_text('100')  # Seleciona 100 itens por página

            driver.execute_script("window.scrollTo(0, 0);")

            sleep(2)

            try:
                WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
                )

                # Executar o comando JavaScript para clicar no checkbox desejado
                driver.execute_script("document.querySelector('thead .form-check-input').click();")
                sleep(1)  # Esperar um momento para ver se o estado muda

                # Verificar o estado do checkbox
                checkbox = driver.find_element(By.CSS_SELECTOR, 'thead .form-check-input')
                is_checked = checkbox.is_selected()
                print(f"O checkbox está marcado: {is_checked}")

            except Exception as e:
                print(f"Ocorreu um erro ao tentar marcar o checkbox: {e}")

            # Verificar se há mais páginas e iterar por elas
            while True:
                try:
                    # Localiza o elemento de paginação
                    paginacao = driver.find_element(By.XPATH,
                                                    '/html/body/app-root/app-layout/div/div[2]/app-nota-substitutiva/div/div[3]/div/div/div[1]/ngb-pagination')

                    # Localiza o botão de próxima página
                    proximaPagina = paginacao.find_element(By.XPATH,
                                                           './/li[@class="page-item ng-star-inserted"]/a[@aria-label="Next"]')

                    # Verifica se o <a> está visível e habilitado
                    if proximaPagina.is_displayed() and proximaPagina.is_enabled():
                        proximaPagina.click()  # Clica na próxima página
                        sleep(1)  # Aguarda o carregamento da nova página

                        checkboxes = driver.find_elements(By.CSS_SELECTOR, 'thead .form-check-input')
                        for checkbox in checkboxes:
                            if not checkbox.is_selected():
                                checkbox.click()  # Marca o checkbox se não estiver selecionado
                        sleep(0.1)  # Aguarde a seleção

                    else:
                        break  # Sai do loop se o botão estiver desabilitado

                except NoSuchElementException:
                    break  # Sai do loop se não houver mais páginas

            sleep(1)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            sleep(1)  # Aguarda um momento após a rolagem

            original_window = driver.current_window_handle

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            imprimir_notas = driver.find_element(By.XPATH,
                                                 '//button[contains(@class, "btn-success") and contains(., "XML Seleção")]')
            imprimir_notas.click()  # Clica no botão de imprimir

            sleep(3)

            if '{"code":2,"error":"Undefined array key 1"}' in driver.page_source:
                print("Erro detectado: 'Undefined array key 1'. Fechando a janela...")
                driver.close()  # Fecha a janela atual
                driver.switch_to.window(driver.window_handles[0])  # Volta para a janela principal


                continue  # Tente novamente

                # Verifique se o download foi bem-sucedido (implemente sua lógica aqui)
            if verificar_download(pastaArquivos):  # Função que verifica se o download foi concluído
                print(f"Download concluído para {name_company}.")
                break  # Saia do loop se o download foi bem-sucedido

            try:
                driver.close()  # Fecha a janela atual
                driver.switch_to.window(driver.window_handles[0])  # Volta para a janela principal
            except Exception as close_error:
                print(f"Erro ao fechar a janela: {close_error}")


        if tentativas == max_tentativas:
            print(f"Falha ao concluir o download após {max_tentativas} tentativas.")

            try:
                downloaded = False
                while not downloaded:
                    NomeParcial = 'NFS'
                    arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                    for arquivo in arquivos_zip:
                        if NomeParcial in arquivo:
                            if verify_downloaded(arquivo):
                                downloaded = True
                                print(f"Download reconhecido: {arquivo}")
                            else:
                                print(f"Download não reconhecido ainda: {arquivo}")
                            sleep(1)

                if downloaded:
                    # Remover arquivos XML antigos
                    NomeParcialPlanilha = 'NFSe'
                    arquivos_planilha_remover = glob.glob(os.path.join(pastaArquivos, '*.xml'))
                    for arquivo in arquivos_planilha_remover:
                        if NomeParcialPlanilha in arquivo and os.path.exists(arquivo):
                            os.remove(arquivo)

                    # Extrair arquivos ZIP
                    for arquivo in arquivos_zip:
                        if NomeParcial in arquivo:
                            with zipfile.ZipFile(arquivo, 'r') as nome_zip:
                                nome_zip.extractall(path=pastaArquivos)  # Extrai todos os arquivos XML sem renomeá-los
                                print(f"Arquivos extraídos de: {arquivo}")  # Mensagem de depuração

                    arquivos_xml = glob.glob(os.path.join(pastaArquivos, '*.xml'))
                    print(f"Arquivos XML encontrados após extração: {arquivos_xml}")  # Depuração

                    # Mover os arquivos XML para a nova pasta
                    for arquivo in os.listdir(pastaArquivos):
                        novo_nome_parcial = 'NFSe20'
                        if arquivo.endswith('.xml') and novo_nome_parcial in arquivo: # Verifica se é um arquivo XML
                            novo_nome = arquivo[-10:]  # Mantém os últimos 6 caracteres
                            novo_nome_completo = f"{novo_nome}"  # Adiciona a extensão .xml
                            caminho_origem = os.path.join(pastaArquivos, arquivo)
                            caminho_destino = os.path.join(pasta_xml_tomados, novo_nome_completo)

                            # Move e renomeia o arquivo
                            shutil.move(caminho_origem, caminho_destino)
                            print(f"Arquivo movido: {caminho_origem} -> {caminho_destino}")

                        else:
                            print(f"Arquivo não encontrado para mover: {arquivo}")  # Depuração
                limpar_pasta(pastaArquivos)

            except Exception as e:
                # Tratamento da exceção
                print(e)
    except Exception as e:
        # Tratamento da exceção
        print(e)
'''


def exec_PDF_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    if not _selecionar_contribuinte(driver, nome_thread, cnpj_cpf):
        return
    _buscar_e_exportar_notas(
        driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos,
        url_lista=URL_NOTAS_PRESTADAS_PVA,
        nome_arquivo_pdf="NFS-e - Prestados.pdf",
        nome_arquivo_xml=None,
        tipo_log="PRESTADOS",
    )

'''def exec_XML_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)
    ultimo_dia = calendar.monthrange(ano, mes)[1]  # Obtém o último dia do mês

    includeLogData(nome_thread,
                   f'NFSE - {name_company}',
                   f'Iniciando processo de download de NFSe de serviços Prestados.',
                   f'{cnpj_cpf}',
                   'PRESTADOS',
                   'info-gradient',
                   'SUCESSO',
                   'success-gradient')

    pasta_xml_prestados = os.path.join(pastaArquivos, 'XML - Prestados')

    # Crie a pasta se não existir
    if not os.path.exists(pasta_xml_prestados):
        os.makedirs(pasta_xml_prestados)
        print(f"Pasta criada: {pasta_xml_prestados}")

    try:
        xml_prestadas = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/notaeletronica'
        driver.get(f'{xml_prestadas}')
        ng_select = WebDriverWait(driver, 9).until(
            EC.presence_of_element_located((By.XPATH, "//ng-select"))
        )
        ng_select.click()

        # Certifique-se de que idDoc está definido antes de usar

        for char in f'{cnpj_cpf}':
            # Espera até que o campo de entrada esteja presente
            campoEntrada = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
            )

            # Envia o texto desejado para o campo de entrada
            campoEntrada.send_keys(cnpj_cpf)  # Envia a string completa

            # Espera que a lista de resultados apareça
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()  # Clica na primeira opção

            # Preencher o campo de data inicial
            campoDatainicial = WebDriverWait(driver, 1).until(
                EC.presence_of_element_located((By.XPATH, '//input[@formcontrolname="nfse_data_inicial"]'))
            )
            campoDatainicial.click()  # Clica no campo de data
            campoDatainicial.clear()  # Limpa o campo antes de digitar
            campoDatainicial.send_keys(f"01/{mes}/{ano}")  # Digita a data no formato desejado
            campoDatainicial.send_keys(Keys.TAB)

            sleep(0.5)

            # Preencher o campo de data final
            campoDatafinal = WebDriverWait(driver, 1).until(
                EC.presence_of_element_located((By.XPATH, '//input[@formcontrolname="nfse_data_final"]'))
            )
            campoDatafinal.click()  # Clica no campo de data
            campoDatafinal.clear()  # Limpa o campo antes de digitar
            campoDatafinal.send_keys(f"{ultimo_dia}/{mes}/{ano}")  # Digita a data no formato desejado
            campoDatafinal.send_keys(Keys.TAB)

            # Selecionar a quantidade de itens por página
            selectQuantidade = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, 'pagination'))  # Ajuste o nome conforme necessário
            )
            select = Select(selectQuantidade)
            select.select_by_visible_text('100')  # Seleciona 100 itens por página
            print("Paginou")
            driver.execute_script("window.scrollTo(0, 0);")
            print("Subiu")
            sleep(2)

            try:
                WebDriverWait(driver, 10).until(
                    EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
                )

                # Executar o comando JavaScript para clicar no checkbox desejado
                driver.execute_script("document.querySelector('thead .form-check-input').click();")
                sleep(1)  # Esperar um momento para ver se o estado muda

                # Verificar o estado do checkbox
                checkbox = driver.find_element(By.CSS_SELECTOR, 'thead .form-check-input')
                is_checked = checkbox.is_selected()
                print(f"O checkbox está marcado: {is_checked}")

            except Exception as e:
                print(f"Ocorreu um erro ao tentar marcar o checkbox: {e}")

            # Verificar se há mais páginas e iterar por elas
            try:
                # Localiza o elemento de paginação
                paginacao = driver.find_element(By.XPATH,
                                                '/html/body/app-root/app-layout/div/div[2]/app-nota-substitutiva/div/div[3]/div/div/div[1]/ngb-pagination')

                # Localiza o botão de próxima página
                proximaPagina = paginacao.find_element(By.XPATH,
                                                       './/a[@aria-label="Next"]')
                print("Encontrou botão de próxima página")

                if proximaPagina.is_displayed() and not proximaPagina.get_attribute("aria-disabled"):
                    proximaPagina.click()  # Clica na próxima página
                    sleep(1)  # Aguarda o carregamento da nova página

                    driver.execute_script("window.scrollTo(0, 0);")
                    print("Subiu")
                    sleep(2)

                    # Espera até que a tabela esteja visível novamente
                    WebDriverWait(driver, 5).until(
                        EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
                    )

                    checkboxes = driver.find_elements(By.CSS_SELECTOR, 'thead .form-check-input')
                    for checkbox in checkboxes:
                        if not checkbox.is_selected():
                            checkbox.click()  # Marca o checkbox se não estiver selecionado
                    sleep(3)  # Aguarde a seleção

                else:
                    break  # Sai do loop se o botão estiver desabilitado

            except NoSuchElementException:
                break  # Sai do loop se não houver mais páginas

            sleep(1)

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            sleep(1)  # Aguarda um momento após a rolagem

            original_window = driver.current_window_handle

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            imprimir_notas = driver.find_element(By.XPATH,
                                                 '//button[contains(@class, "btn-success") and contains(., "XML Seleção")]')
            imprimir_notas.click()  # Clica no botão de imprimir

            try:
                downloaded = False
                while not downloaded:
                    NomeParcial = 'NFS'
                    arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                    for arquivo in arquivos_zip:
                        if NomeParcial in arquivo:
                            if verify_downloaded(arquivo):
                                downloaded = True
                                print(f"Download reconhecido: {arquivo}")
                            else:
                                print(f"Download não reconhecido ainda: {arquivo}")
                            sleep(1)

                if downloaded:
                    # Remover arquivos XML antigos
                    NomeParcialPlanilha = 'NFSe'
                    arquivos_planilha_remover = glob.glob(os.path.join(pastaArquivos, '*.xml'))
                    for arquivo in arquivos_planilha_remover:
                        if NomeParcialPlanilha in arquivo and os.path.exists(arquivo):
                            os.remove(arquivo)

                    # Extrair arquivos ZIP
                    for arquivo in arquivos_zip:
                        if NomeParcial in arquivo:
                            with zipfile.ZipFile(arquivo, 'r') as nome_zip:
                                nome_zip.extractall(path=pastaArquivos)  # Extrai todos os arquivos XML sem renomeá-los
                                print(f"Arquivos extraídos de: {arquivo}")  # Mensagem de depuração

                    arquivos_xml = glob.glob(os.path.join(pastaArquivos, '*.xml'))
                    print(f"Arquivos XML encontrados após extração: {arquivos_xml}")  # Depuração

                    # Mover os arquivos XML para a nova pasta

                    for arquivo in os.listdir(pastaArquivos):
                        novo_nome_parcial = 'NFSe20'
                        if arquivo.endswith('.xml') and novo_nome_parcial in arquivo: # Verifica se é um arquivo XML
                            novo_nome = arquivo[-10:]  # Mantém os últimos 6 caracteres
                            novo_nome_completo = f"{novo_nome}"  # Adiciona a extensão .xml
                            caminho_origem = os.path.join(pastaArquivos, arquivo)
                            caminho_destino = os.path.join(pasta_xml_prestados, novo_nome_completo)

                            # Move e renomeia o arquivo
                            shutil.move(caminho_origem, caminho_destino)
                            print(f"Arquivo movido: {caminho_origem} -> {caminho_destino}")

                        else:
                            print(f"Arquivo não encontrado para mover: {arquivo}")  # Depuração

            except Exception as e:
                # Tratamento da exceção
                print(e)
    except Exception as e:
    # Tratamento da exceção
        print(e)'''

def exec_GUIAISSQN(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    try:
        home_page = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/movimento'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()
        print('GUIAISSQN - Executando')
        erro = False

        ng_select = WebDriverWait(driver, 9).until(
            EC.presence_of_element_located((By.XPATH, "//ng-select"))
        )
        ng_select.click()

        # Certifique-se de que idDoc está definido antes de usar

        for char in f'{cnpj_cpf}':
            # Espera até que o campo de entrada esteja presente
            campoEntrada = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
            )

            # Envia o texto desejado para o campo de entrada
            campoEntrada.send_keys(cnpj_cpf)  # Envia a string completa

            # Espera que a lista de resultados apareça
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()  # Clica na primeira opção

            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{mes}/{ano}").perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)

            sleep(5)

            driver.execute_script("window.scrollTo(0, 0);")
            sleep(5)

            radio_button = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='selected']"))
            )

            # Usar JavaScript para clicar no botão de rádio
            driver.execute_script("arguments[0].click();", radio_button)
            print("Botão de rádio clicado com sucesso usando JavaScript.")

            sleep(5)

            botao_segunda_via = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(@class, 'btn-info') and contains(text(), 'Segunda Via')]"))
            )
            botao_segunda_via.click()  # Clica no botão
            print("Botão 'Segunda Via' clicado com sucesso.")

            sleep(6)

            div_imprimir = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//div[contains(@class, 'btn') and contains(text(), 'Imprimir')]"))
            )
            div_imprimir.click()  # Clica na <div>
            print("Elemento 'Imprimir' clicado com sucesso.")

            sleep(3)

            caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "GUIA ISSQN.pdf", intervalo=5)

            # Verifica se o arquivo foi baixado com sucesso
            if os.path.exists(caminho_pdf):
                print("PDF baixado e renomeado com sucesso:", caminho_pdf)

                # Registrar log de sucesso
                includeLogData(nome_thread,
                               f'GUIA ISSQN - {name_company}',
                               f'PDF de GUIA ISSQN baixado com sucesso.',
                               f'{cnpj_cpf}',
                               'GUIA ISSQN',
                               'info-gradient',
                               'SUCESSO',
                               'success-gradient')

            else:
                print("Erro: O PDF não foi baixado.")
                includeLogData(nome_thread,
                f'GUIA ISSQN - {name_company}',
                f'Erro ao baixar GUIA ISSQN.',
                f'{cnpj_cpf}',
                'GUIA ISSQN',
                'info-gradient',
                'ATENÇÃO',
                'warning-gradient')

        else:
            print("Dropdown de tipo de escrituração não está habilitado.")
    except Exception as e:
        print(f"Erro geral na execução do PDF: {e}")

        # Salvar captura de tela em caso de erro
        driver.execute_script("document.body.style.zoom = '75%'")
        pasta_destino = f"{pastaArquivos}/ERRO PDF NFSE PRESTADO.png"
        if os.path.exists(pasta_destino):
            os.remove(pasta_destino)
        driver.save_screenshot(pasta_destino)
        driver.execute_script("document.body.style.zoom = '100%'")
        limpar_pasta(pastaArquivos)


def exec_ENC_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    try:
        home_page = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/fechamento'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()
        print('Encerramento Tomados - Executando')
        erro = False

        ng_select = WebDriverWait(driver, 9).until(
            EC.presence_of_element_located((By.XPATH, "//ng-select"))
        )
        ng_select.click()

        for char in f'{cnpj_cpf}':
            campoEntrada = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
            )
            campoEntrada.send_keys(cnpj_cpf)
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()

            ng_select = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-select[@formcontrolname="tipo"]'))
            )

            if ng_select.is_enabled():
                ng_select.click()
                sleep(5)

                opcao_fiscal = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, '//div[contains(@class, "ng-option") and contains(.//span, "Serviço Tomado")]'))
                )
                opcao_fiscal.click()

            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{mes}/{ano}").perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()

            sleep(3)

            try:
                elemento_nenhum_registro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//h6[text()='NÃO CONSTA REGISTRO DE FECHAMENTO PARA A REFERÊNCIA.']")
                    )
                )
                # Se o elemento estiver presente, seguir o fluxo de declaração sem movimento
                checkbox_label = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//label[contains(text(), 'Aceito declaração \"Sem Movimento\"')]"))
                )
                # Clicar no checkbox através do label
                checkbox_label.click()
                sleep(1)

                botao_declarar = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Declarar Sem Movimento')]"))
                )
                botao_declarar.click()
                print("Botão 'Declarar Sem Movimento' clicado. Aguardando download do PDF...")

                # ✅ AGUARDAR ATÉ 10 SEGUNDOS PELA MENSAGEM DE ERRO
                sleep(4)

                # ✅ VERIFICAR SE APARECEU A MENSAGEM "FECHAMENTO SEM MOVIMENTO JÁ EFETUADO"
                try:
                    mensagem_erro = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH,
                                                        "//span[@data-notify='message' and contains(text(), 'Fechamento sem movimento já efetuado!')]"))
                    )
                    print(
                        "Detectada mensagem: 'Fechamento sem movimento já efetuado!' - Navegando para página de movimento...")

                    # ✅ NAVEGAR PARA PÁGINA DE MOVIMENTO
                    driver.get('https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/movimento')
                    sleep(3)

                    # ✅ PREENCHER EMPRESA
                    ng_select_movimento = WebDriverWait(driver, 9).until(
                        EC.presence_of_element_located((By.XPATH, "//ng-select"))
                    )
                    ng_select_movimento.click()

                    campoEntrada_movimento = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
                    )
                    campoEntrada_movimento.send_keys(cnpj_cpf)

                    WebDriverWait(driver, 2).until(
                        EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
                    )
                    sleep(2)

                    primeiraOpcao_movimento = WebDriverWait(driver, 1).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
                    )
                    primeiraOpcao_movimento.click()

                    # ✅ PREENCHER DATA
                    actions.send_keys(Keys.TAB).perform()
                    sleep(0.5)
                    actions.send_keys(f"{mes}/{ano}").perform()
                    sleep(0.5)
                    actions.send_keys(Keys.TAB).perform()
                    sleep(3)

                    # ✅ PROCURAR E SELECIONAR RADIO BUTTON PARA "ESCRITURAÇÃO SUBSTITUTIVA" COM SITUAÇÃO "SEM MOVIMENTO"
                    try:
                        # ✅ XPATH CORRIGIDO BASEADO NO HTML REAL
                        radio_button = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH,
                                                            "//tr[td[contains(text(), 'Escrituração Substitutiva')] and td[contains(text(), 'Sem movimento')]]//input[@type='radio' and @name='selected']"
                                                            ))
                        )

                        # ✅ USAR JAVASCRIPT PARA CLICAR NO RADIO BUTTON
                        driver.execute_script("arguments[0].click();", radio_button)
                        print(
                            "Radio button selecionado para 'Escrituração Substitutiva' com situação 'Sem movimento' usando JavaScript.")

                        sleep(5)

                        # ✅ CLICAR NO BOTÃO "IMPRIMIR SEM MOVIMENTO"
                        botao_imprimir = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(
                                (By.XPATH,
                                 "//button[contains(@class, 'btn-info') and contains(text(), 'Imprimir Sem Movimento')]")
                            )
                        )
                        botao_imprimir.click()
                        print("Botão 'Imprimir Sem Movimento' clicado com sucesso.")

                        sleep(6)

                        # ✅ ESPERAR PELO DOWNLOAD E RENOMEAR ARQUIVO
                        caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "DEC. SEM MOVIMENTO - TOMADOS.pdf",
                                                                 intervalo=15)
                        if caminho_pdf:
                            print(f"Arquivo renomeado para: {caminho_pdf}")
                        else:
                            print("Falha ao renomear o arquivo.")

                        print("Processo de movimento para TOMADOS concluído.")

                    except Exception as e:
                        print(f"Erro ao selecionar radio button na página de movimento: {e}")

                except TimeoutException:
                    # Não apareceu a mensagem de erro, continuar com download normal
                    print("Mensagem de erro não detectada, continuando com download...")

                    # Espera pelo download do arquivo e renomeia
                    caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "DEC. SEM MOVIMENTO - TOMADOS.pdf",
                                                             intervalo=15)
                    if caminho_pdf:
                        print(f"Arquivo renomeado para: {caminho_pdf}")
                    else:
                        print("Falha ao renomear o arquivo.")

            except TimeoutException:
                print("Registro encontrado, prosseguindo com o fluxo normal.")

                try:
                    WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
                    )

                    driver.execute_script("document.querySelector('thead .form-check-input').click();")
                    sleep(1)

                    checkbox = driver.find_element(By.CSS_SELECTOR, 'thead .form-check-input')
                    is_checked = checkbox.is_selected()
                    print(f"O checkbox está marcado: {is_checked}")

                except Exception as e:
                    print(f"Ocorreu um erro ao tentar marcar o checkbox: {e}")

                sleep(2)

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                sleep(3)

                # Clicar no botão "Concluir Fechamento"
                botaoConcluir = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '.btn.btn-success'))
                )
                botaoConcluir.click()
                sleep(2)

                # Captura de tela
                driver.execute_script("document.body.style.zoom = '75%'")
                pasta_destino = f"{pastaArquivos}/Encerramento NFSE Tomadas - sucesso.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                driver.execute_script("document.body.style.zoom = '100%'")

            except Exception as e:
                print(f"Ocorreu um erro na execução: {e}")

    except Exception as e:
        print(f"Ocorreu um erro na execução: {e}")


def exec_ENC_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    try:
        home_page = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/fechamento'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()
        print('Encerramento Prestados - Executando')
        erro = False

        ng_select = WebDriverWait(driver, 9).until(
            EC.presence_of_element_located((By.XPATH, "//ng-select"))
        )
        ng_select.click()

        for char in f'{cnpj_cpf}':
            campoEntrada = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
            )
            campoEntrada.send_keys(cnpj_cpf)
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()

            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{mes}/{ano}").perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()

            sleep(3)

            try:
                # Verifica se não há registro
                elemento_nenhum_registro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//h6[text()='NÃO CONSTA REGISTRO DE FECHAMENTO PARA A REFERÊNCIA.']")
                    )
                )
                # Se o elemento estiver presente, seguir o fluxo de declaração sem movimento
                checkbox_label = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//label[contains(text(), 'Aceito declaração \"Sem Movimento\"')]"))
                )
                checkbox_label.click()
                sleep(1)

                botao_declarar = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Declarar Sem Movimento')]"))
                )
                botao_declarar.click()
                print("Botão 'Declarar Sem Movimento' clicado. Aguardando download do PDF...")

                # ✅ AGUARDAR ATÉ 10 SEGUNDOS PELA MENSAGEM DE ERRO
                sleep(4)

                # ✅ VERIFICAR SE APARECEU A MENSAGEM "FECHAMENTO SEM MOVIMENTO JÁ EFETUADO"
                try:
                    mensagem_erro = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH,
                                                        "//span[@data-notify='message' and contains(text(), 'Fechamento sem movimento já efetuado!')]"))
                    )
                    print(
                        "Detectada mensagem: 'Fechamento sem movimento já efetuado!' - Navegando para página de movimento...")

                    # ✅ NAVEGAR PARA PÁGINA DE MOVIMENTO
                    driver.get('https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/movimento')
                    sleep(3)

                    # ✅ PREENCHER EMPRESA
                    ng_select_movimento = WebDriverWait(driver, 9).until(
                        EC.presence_of_element_located((By.XPATH, "//ng-select"))
                    )
                    ng_select_movimento.click()

                    campoEntrada_movimento = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
                    )
                    campoEntrada_movimento.send_keys(cnpj_cpf)

                    WebDriverWait(driver, 2).until(
                        EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
                    )
                    sleep(2)

                    primeiraOpcao_movimento = WebDriverWait(driver, 1).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
                    )
                    primeiraOpcao_movimento.click()

                    # ✅ PREENCHER DATA
                    actions.send_keys(Keys.TAB).perform()
                    sleep(0.5)
                    actions.send_keys(f"{mes}/{ano}").perform()
                    sleep(0.5)
                    actions.send_keys(Keys.TAB).perform()
                    sleep(3)

                    # ✅ PROCURAR E SELECIONAR RADIO BUTTON PARA "ESCRITURAÇÃO FISCAL" COM SITUAÇÃO "SEM MOVIMENTO"
                    try:
                        # ✅ XPATH CORRIGIDO BASEADO NO HTML REAL
                        radio_button = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH,
                                                            "//tr[td[contains(text(), 'Escrituração Fiscal')] and td[contains(text(), 'Sem movimento')]]//input[@type='radio' and @name='selected']"
                                                            ))
                        )

                        # ✅ USAR JAVASCRIPT PARA CLICAR NO RADIO BUTTON
                        driver.execute_script("arguments[0].click();", radio_button)
                        print(
                            "Radio button selecionado para 'Escrituração Fiscal' com situação 'Sem movimento' usando JavaScript.")

                        sleep(5)

                        # ✅ CLICAR NO BOTÃO "IMPRIMIR SEM MOVIMENTO"
                        botao_imprimir = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(
                                (By.XPATH,
                                 "//button[contains(@class, 'btn-info') and contains(text(), 'Imprimir Sem Movimento')]")
                            )
                        )
                        botao_imprimir.click()
                        print("Botão 'Imprimir Sem Movimento' clicado com sucesso.")

                        sleep(6)

                        # ✅ ESPERAR PELO DOWNLOAD E RENOMEAR ARQUIVO
                        caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "DEC. SEM MOVIMENTO - PRESTADOS.pdf",
                                                                 intervalo=15)
                        if caminho_pdf:
                            print(f"Arquivo renomeado para: {caminho_pdf}")
                        else:
                            print("Falha ao renomear o arquivo.")

                        print("Processo de movimento para PRESTADOS concluído.")

                    except Exception as e:
                        print(f"Erro ao selecionar radio button na página de movimento: {e}")

                except TimeoutException:
                    # Não apareceu a mensagem de erro, continuar com download normal
                    print("Mensagem de erro não detectada, continuando com download...")

                    # Espera pelo download do arquivo e renomeia
                    caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "DEC. SEM MOVIMENTO - PRESTADOS.pdf",
                                                             intervalo=15)
                    if caminho_pdf:
                        print(f"Arquivo renomeado para: {caminho_pdf}")
                    else:
                        print("Falha ao renomear o arquivo.")

            except TimeoutException:
                print("Registro encontrado, prosseguindo com o fluxo normal.")

                try:
                    WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
                    )

                    driver.execute_script("document.querySelector('thead .form-check-input').click();")
                    sleep(1)

                    checkbox = driver.find_element(By.CSS_SELECTOR, 'thead .form-check-input')
                    is_checked = checkbox.is_selected()
                    print(f"O checkbox está marcado: {is_checked}")

                except Exception as e:
                    print(f"Ocorreu um erro ao tentar marcar o checkbox: {e}")

                sleep(2)

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                sleep(3)

                # Clicar no botão "Concluir Fechamento"
                botaoConcluir = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '.btn.btn-success'))
                )
                botaoConcluir.click()
                sleep(2)

                # Captura de tela
                driver.execute_script("document.body.style.zoom = '75%'")
                pasta_destino = f"{pastaArquivos}/Encerramento NFSE Prestados - sucesso.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                driver.execute_script("document.body.style.zoom = '100%'")

            except Exception as e:
                print(f"Ocorreu um erro na execução: {e}")

    except Exception as e:
        print(f"Ocorreu um erro na execução: {e}")

    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    try:
        home_page = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/fechamento'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()
        print('Encerramento Prestados - Executando')
        erro = False

        ng_select = WebDriverWait(driver, 9).until(
            EC.presence_of_element_located((By.XPATH, "//ng-select"))
        )
        ng_select.click()

        for char in f'{cnpj_cpf}':
            campoEntrada = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
            )
            campoEntrada.send_keys(cnpj_cpf)
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()

            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{mes}/{ano}").perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()

            sleep(3)

            try:
                # Verifica se não há registro
                elemento_nenhum_registro = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//h6[text()='NÃO CONSTA REGISTRO DE FECHAMENTO PARA A REFERÊNCIA.']")
                    )
                )
                # Se o elemento estiver presente, seguir o fluxo de declaração sem movimento
                checkbox_label = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//label[contains(text(), 'Aceito declaração \"Sem Movimento\"')]"))
                )
                checkbox_label.click()
                sleep(1)

                botao_declarar = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Declarar Sem Movimento')]"))
                )
                botao_declarar.click()
                print("Botão 'Declarar Sem Movimento' clicado. Aguardando download do PDF...")

                # ✅ AGUARDAR ATÉ 10 SEGUNDOS PELA MENSAGEM DE ERRO
                sleep(10)

                # ✅ VERIFICAR SE APARECEU A MENSAGEM "FECHAMENTO SEM MOVIMENTO JÁ EFETUADO"
                try:
                    mensagem_erro = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH,
                                                        "//span[@data-notify='message' and contains(text(), 'Fechamento sem movimento já efetuado!')]"))
                    )
                    print(
                        "Detectada mensagem: 'Fechamento sem movimento já efetuado!' - Navegando para página de movimento...")

                    # ✅ NAVEGAR PARA PÁGINA DE MOVIMENTO
                    driver.get('https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/movimento')
                    sleep(3)

                    # ✅ PREENCHER EMPRESA
                    ng_select_movimento = WebDriverWait(driver, 9).until(
                        EC.presence_of_element_located((By.XPATH, "//ng-select"))
                    )
                    ng_select_movimento.click()

                    campoEntrada_movimento = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
                    )
                    campoEntrada_movimento.send_keys(cnpj_cpf)

                    WebDriverWait(driver, 2).until(
                        EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
                    )
                    sleep(2)

                    primeiraOpcao_movimento = WebDriverWait(driver, 1).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
                    )
                    primeiraOpcao_movimento.click()

                    # ✅ PREENCHER DATA
                    actions.send_keys(Keys.TAB).perform()
                    sleep(0.5)
                    actions.send_keys(f"{mes}/{ano}").perform()
                    sleep(0.5)
                    actions.send_keys(Keys.TAB).perform()
                    sleep(3)

                    # ✅ PROCURAR E SELECIONAR RADIO BUTTON PARA "ESCRITURAÇÃO FISCAL" COM SITUAÇÃO "SEM MOVIMENTO"
                    try:
                        # Encontrar todas as linhas da tabela
                        linhas_tabela = driver.find_elements(By.XPATH, "//tr[contains(@class, 'ng-star-inserted')]")

                        radio_button_encontrado = False
                        for linha in linhas_tabela:
                            try:
                                # Verificar se é "Escrituração Fiscal"
                                tipo_escrituracao = linha.find_element(By.XPATH,
                                                                       ".//td[@class='text-start' and contains(text(), 'Escrituração Fiscal')]")

                                # Verificar se a situação é "Sem movimento"
                                situacao = linha.find_element(By.XPATH,
                                                              ".//td[@class='text-center' and contains(text(), 'Sem movimento')]")

                                # Se ambas as condições forem atendidas, selecionar o radio button
                                radio_button = linha.find_element(By.XPATH,
                                                                  ".//input[@type='radio' and @name='selected' and @class='form-check-input']")

                                # ✅ USAR JAVASCRIPT PARA CLICAR NO RADIO BUTTON
                                driver.execute_script("arguments[0].click();", radio_button)
                                print(
                                    "Radio button selecionado para 'Escrituração Fiscal' com situação 'Sem movimento' usando JavaScript.")
                                radio_button_encontrado = True
                                break

                            except NoSuchElementException:
                                continue

                        if radio_button_encontrado:
                            sleep(5)

                            # ✅ CLICAR NO BOTÃO "IMPRIMIR SEM MOVIMENTO"
                            botao_imprimir = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable(
                                    (By.XPATH,
                                     "//button[contains(@class, 'btn-info') and contains(text(), 'Imprimir Sem Movimento')]")
                                )
                            )
                            botao_imprimir.click()
                            print("Botão 'Imprimir Sem Movimento' clicado com sucesso.")

                            sleep(6)

                            # ✅ ESPERAR PELO DOWNLOAD E RENOMEAR ARQUIVO
                            caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos,
                                                                     "DEC. SEM MOVIMENTO - PRESTADOS.pdf", intervalo=15)
                            if caminho_pdf:
                                print(f"Arquivo renomeado para: {caminho_pdf}")
                            else:
                                print("Falha ao renomear o arquivo.")
                        else:
                            print("Radio button para 'Escrituração Fiscal' com 'Sem movimento' não encontrado.")

                        print("Processo de movimento para PRESTADOS concluído.")

                    except Exception as e:
                        print(f"Erro ao selecionar radio button na página de movimento: {e}")

                except TimeoutException:
                    # Não apareceu a mensagem de erro, continuar com download normal
                    print("Mensagem de erro não detectada, continuando com download...")

                    # Espera pelo download do arquivo e renomeia
                    caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "DEC. SEM MOVIMENTO - PRESTADOS.pdf",
                                                             intervalo=15)
                    if caminho_pdf:
                        print(f"Arquivo renomeado para: {caminho_pdf}")
                    else:
                        print("Falha ao renomear o arquivo.")

            except TimeoutException:
                print("Registro encontrado, prosseguindo com o fluxo normal.")

                try:
                    WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
                    )

                    driver.execute_script("document.querySelector('thead .form-check-input').click();")
                    sleep(1)

                    checkbox = driver.find_element(By.CSS_SELECTOR, 'thead .form-check-input')
                    is_checked = checkbox.is_selected()
                    print(f"O checkbox está marcado: {is_checked}")

                except Exception as e:
                    print(f"Ocorreu um erro ao tentar marcar o checkbox: {e}")

                sleep(2)

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                sleep(3)

                # Clicar no botão "Concluir Fechamento"
                botaoConcluir = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '.btn.btn-success'))
                )
                botaoConcluir.click()
                sleep(2)

                # Captura de tela
                driver.execute_script("document.body.style.zoom = '75%'")
                pasta_destino = f"{pastaArquivos}/Encerramento NFSE Prestados - sucesso.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                driver.execute_script("document.body.style.zoom = '100%'")

            except Exception as e:
                print(f"Ocorreu um erro na execução: {e}")

    except Exception as e:
        print(f"Ocorreu um erro na execução: {e}")



def exec_NFSE_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    if not _selecionar_contribuinte(driver, nome_thread, cnpj_cpf):
        return
    _buscar_e_exportar_notas(
        driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos,
        url_lista=URL_NOTAS_TOMADAS_PVA,
        nome_arquivo_pdf="NOTAS - Tomados.pdf",
        nome_arquivo_xml="NFSe - Tomados.xml",  # extensao nao confirmada ao vivo, ver _buscar_e_exportar_notas
        tipo_log="TOMADOS",
    )


def exec_NFSE_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    if not _selecionar_contribuinte(driver, nome_thread, cnpj_cpf):
        return
    _buscar_e_exportar_notas(
        driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos,
        url_lista=URL_NOTAS_PRESTADAS_PVA,
        nome_arquivo_pdf="NOTAS - Prestados.pdf",
        nome_arquivo_xml="NFSe - Prestados.xml",  # extensao nao confirmada ao vivo, ver _buscar_e_exportar_notas
        tipo_log="PRESTADOS",
    )


def _nao_migrado(nome_thread, name_company, cnpj_cpf, tipo_log, url_conhecida, o_que_falta):
    """GUIA ISSQN e Declaração (ENC_TOMADOS/ENC_PRESTADOS) foram
    localizadas no portal novo em 01/09/2026 mas não terminadas -- ver
    docs/rpa-refactor-plan.md (mesmo mapeamento vale pro projeto Zaya, que
    tem os ids reais encontrados até agora). Falha alto e claro em vez de
    tentar contra a URL antiga (que não existe mais) ou adivinhar um fluxo
    não validado."""
    print(f"{tipo_log} - {name_company}: portal novo ainda não migrado ({o_que_falta}). Tela: {url_conhecida}")
    includeLogData(nome_thread,
                   f'{tipo_log} - {name_company}',
                   f'Não migrado pro portal novo ainda -- {o_que_falta}. Tela conhecida: {url_conhecida}.',
                   cnpj_cpf,
                   tipo_log,
                   'info-gradient',
                   'ATENÇÃO',
                   'warning-gradient')


def exec_GUIAISSQN(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    _nao_migrado(
        nome_thread, name_company, cnpj_cpf, 'GUIA ISSQN',
        url_conhecida='https://iss.primaveradoleste.mt.gov.br/issweb/paginas/admin/guia/emitir',
        o_que_falta=(
            "o dropdown 'Movimento' (Tipo\u2192Ano\u2192M\u00eas\u2192Movimento) \u00e9 "
            "populado via AJAX em cascata e n\u00e3o populou de forma confi\u00e1vel na "
            "inspe\u00e7\u00e3o ao vivo, mesmo com cliques reais -- ver "
            "/paginas/admin/guia/consultar (guias j\u00e1 emitidas, 2\u00aa via) como "
            "alternativa mais simples a explorar antes de tentar 'emitir' de novo"
        ),
    )


def exec_ENC_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    _nao_migrado(
        nome_thread, name_company, cnpj_cpf, 'ENCERRAMENTO TOMADOS',
        url_conhecida='https://iss.primaveradoleste.mt.gov.br/issweb/paginas/admin/declaracoes/tomador/movimentos',
        o_que_falta=(
            "fluxo de v\u00e1rias etapas (bot\u00e3o 'Novo Movimento' "
            "frmActions:cbAbrir \u2192 lan\u00e7ar notas ou declarar sem movimento \u2192 "
            "fechar) n\u00e3o foi percorrido at\u00e9 o fim na inspe\u00e7\u00e3o ao vivo"
        ),
    )


def exec_ENC_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    # Na tela de sele\u00e7\u00e3o de contribuinte, a coluna "Dec Prest?" veio "N\u00e3o
    # Declara" pra INTEGRA CONSULTORIA (a empresa usada na inspe\u00e7\u00e3o) -- sinal
    # (n\u00e3o confirmado pra outras empresas/regimes) de que o portal novo pode
    # nem ter um equivalente de "encerramento prestados" -- quem emite NFS-e
    # como prestador talvez n\u00e3o precise de declara\u00e7\u00e3o de fechamento
    # separada. Falhando alto e claro em vez de assumir isso silenciosamente.
    _nao_migrado(
        nome_thread, name_company, cnpj_cpf, 'ENCERRAMENTO PRESTADOS',
        url_conhecida='https://iss.primaveradoleste.mt.gov.br/issweb/paginas/admin/declaracoes/tomador/movimentos',
        o_que_falta=(
            "n\u00e3o existe 'Declara\u00e7\u00e3o Prestador' vis\u00edvel no menu do portal novo "
            "(s\u00f3 'Declara\u00e7\u00e3o Tomador') -- precisa confirmar se prestador "
            "realmente n\u00e3o precisa de fechamento separado antes de decidir o "
            "que portar aqui"
        ),
    )


if __name__ == "__main__":
    import sys

    # print() com emoji (varios ja existentes no arquivo) quebra em
    # console Windows com codepage cp1252 -- forca UTF-8 no stdout/stderr
    # so quando rodado standalone (nao afeta o comportamento sob Flask).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if "--login-manual" in sys.argv:
        print("Abrindo Chrome (janela visível) no perfil persistente...")
        print(f"Perfil: {PERFIL_CHROME_PERSISTENTE}")
        driver = IniciarDriver(headless=False)
        try:
            driver.get(URL_LOGIN_PVA)
            print(f"\nNavegador aberto em {URL_LOGIN_PVA}.")
            print("Clique em 'Entrar com certificado digital' e escolha o certificado -- clique real, de verdade.")
            print("Se pedir para instalar a extensão 'Fiorilli Web Extension' nesse perfil, instale (só na primeira vez).")
            input("\nDepois de logar (a página não deve mais mostrar o formulário de login), aperte Enter aqui...")
            if "/paginas/login" in driver.current_url:
                print("\nAINDA está na página de login -- o login não parece ter completado. Tente de novo.")
            else:
                print(f"\nSessão salva no perfil persistente. URL atual: {driver.current_url}")
                print("As próximas execuções automáticas (exec_LOGIN) vão reaproveitar essa sessão até ela expirar.")
        finally:
            driver.quit()

    elif "--verificar" in sys.argv:
        # Igual --login-manual, mas SEM esperar Enter no terminal (poll no
        # lugar) -- pra rodar de um jeito que não depende de alguém digitar
        # no mesmo terminal que abriu o navegador (ex: Claude rodando isto
        # via ferramenta de shell, humano só clica o certificado na janela
        # que aparece). Depois de detectar login, roda o fluxo real
        # (selecionar contribuinte + baixar notas prestadas) contra um
        # cliente com dados conhecidos, pra provar (ou não) que o resto do
        # pipeline funciona de ponta a ponta, não só o login.
        import tempfile

        print("Abrindo Chrome (janela visível) no perfil persistente...")
        print(f"Perfil: {PERFIL_CHROME_PERSISTENTE}")
        driver = IniciarDriver(headless=False)
        try:
            driver.get(URL_LOGIN_PVA)
            print(f"\nNavegador aberto em {URL_LOGIN_PVA}.")
            print("Clique em 'Entrar com certificado digital' e escolha o certificado -- clique real, de verdade.")
            print("Esperando você logar (sem limite de tempo pra digitar nada aqui, só clicar lá na janela)...")

            logado = False
            for _ in range(150):  # ~10 minutos (150 x 4s)
                sleep(4)
                if "/paginas/login" not in driver.current_url:
                    logado = True
                    break
                print(".", end="", flush=True)

            print()
            if not logado:
                print("\nTempo esgotado sem detectar login. Rode de novo quando tiver o certificado à mão.")
            else:
                print(f"\nLogin detectado! URL atual: {driver.current_url}")
                print("\nTestando o fluxo completo: selecionar contribuinte + baixar notas prestadas...")
                print("(cliente de teste: INTEGRA CONSULTORIA AGRONOMICA, CNPJ 14497919000147, competência 10/2024)")

                pasta_teste = os.path.join(tempfile.gettempdir(), "onix_teste_verificar_pva")
                os.makedirs(pasta_teste, exist_ok=True)

                if not _selecionar_contribuinte(driver, "teste-verificar", "14497919000147"):
                    print("\nFALHOU: não conseguiu selecionar o contribuinte de teste.")
                else:
                    sucesso = _buscar_e_exportar_notas(
                        driver, "teste-verificar", "INTEGRA CONSULTORIA AGRONOMICA (teste)",
                        "14497919000147", "10", "2024", pasta_teste,
                        url_lista=URL_NOTAS_PRESTADAS_PVA,
                        nome_arquivo_pdf="NOTAS - Prestados.pdf",
                        nome_arquivo_xml="NFSe - Prestados.xml",
                        tipo_log="TESTE-PRESTADOS",
                    )
                    arquivos = os.listdir(pasta_teste)
                    print(f"\nResultado: {'SUCESSO' if sucesso else 'FALHOU'}")
                    print(f"Pasta de teste: {pasta_teste}")
                    print(f"Arquivos encontrados: {arquivos}")
        finally:
            driver.quit()

    else:
        print("Uso:")
        print("  python -m OnixWeb.rpautomation.prefeituras.MT_1 --login-manual")
        print("      Abre o navegador, você loga com certificado, aperta Enter aqui pra confirmar.")
        print("  python -m OnixWeb.rpautomation.prefeituras.MT_1 --verificar")
        print("      Igual, mas sem precisar apertar Enter -- detecta o login sozinho e já testa")
        print("      o fluxo completo (selecionar contribuinte + baixar notas) contra um cliente real.")
