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


def IniciarDriver():
 import os
 import tempfile
 import uuid
 import threading

 caminho_driver = os.path.join(
  root_path,
  r"OnixWeb\rpautomation\dependencias\chromedriver\chromedriver.exe"
 )

 print(f"🔧 ChromeDriver usado: {caminho_driver}")
 print(f"🔧 ChromeDriver existe? {os.path.exists(caminho_driver)}")

 chrome_options = Options()

 # Perfil exclusivo por execução para evitar travamento em data:,
 nome_thread = threading.current_thread().name
 perfil_chrome = os.path.join(
  tempfile.gettempdir(),
  f"onix_chrome_profile_{nome_thread}_{uuid.uuid4().hex}"
 )

 chrome_options.add_argument(f"--user-data-dir={perfil_chrome}")
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

    # Lista de arquivos que devem ser ignorados
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

        # Verifica se há algum arquivo PDF disponível (excluindo os da lista)
        for arquivo in arquivos:
            if arquivo.endswith(".pdf") and arquivo not in arquivos_excluidos:
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

def exec_LOGIN(driver, nome_thread, login_prefeitura, senha_prefeitura):
    includeLogData(nome_thread,
                   f'LOGIN - CONTABILISTA',
                   f'Realizando login...',
                   f'BOT',
                   'PREFEITURA DE PRIMAVERA DO LESTE',
                   'warning-gradient',
                   'ATENÇÃO',
                   'warning-gradient')
    actions = ActionChains(driver)
    prefpva = "https://cidadaoonline.primaveradoleste.mt.gov.br/app/pages/login-nfe"

    logado = False

    try:
        driver.get(prefpva)

        # Aguarda até que o formulário de login esteja presente
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//app-login/form")))

        # Encontra o campo de login e insere o valor
        login_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@name='username']")))  # Ajuste o nome do campo se necessário
        login_field.send_keys(login_prefeitura)

        # Encontra o campo de senha e insere o valor
        password_field = WebDriverWait(driver, 10).until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@name='password']")))  # Ajuste o nome do campo se necessário
        password_field.send_keys(senha_prefeitura)

        # Encontra e clica no botão de login
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button")))  # Ajuste o seletor se necessário
        submit_button.click()

        # Verifica se o login foi bem-sucedido
        WebDriverWait(driver, 10).until(EC.url_to_be(
            'https://cidadaoonline.primaveradoleste.mt.gov.br/app/dashboard'))  # Ajuste a URL de redirecionamento
        logado = True

    except Exception as e:
        print(f"Erro durante o login: {e}")
        logado = False  # Garante que logado seja False em caso de erro

    includeLogData(nome_thread,
                'LOGIN - CONTABILISTA',
                'Acesso realizado com sucesso.',
                'BOT',
                'PREFEITURA DE PRIMAVERA DO LESTE',
                'warning-gradient',
                'SUCESSO',
                'success-gradient')
    print('logou PREFEITURA')
    return logado


def exec_PDF_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    try:
        # URL do relatório
        tomados_relatorio2 = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/relatorios/notasescrituradas'
        driver.get(tomados_relatorio2)

        # Espera pelo dropdown de tipo de escrituração
        ng_select = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//ng-select[@formcontrolname="tipo_escrituracao"]'))
        )

        if ng_select.is_enabled():
            ng_select.click()
            sleep(5)

            # Seleciona a opção "Substitutiva (Serviço Tomado)"
            opcao_fiscal = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                                            '//div[contains(@class, "ng-option") and contains(.//span, "Substitutiva (Serviço Tomado)")]'))
            )
            opcao_fiscal.click()

            # Preenche os campos necessários
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{mes}/{ano}").perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.3)
            actions.send_keys(f"{mes}/{ano}").perform()
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{cnpj_cpf}").perform()

            # Espera que a lista de resultados apareça e seleciona a primeira opção
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()  # Clica na primeira opção

            # Clica no botão "Imprimir"
            imprimir_relatorio = driver.find_element(By.XPATH,
                                                     '//button[contains(@class, "btn-success") and contains(., "Imprimir")]')
            imprimir_relatorio.click()  # Clica no botão de imprimir

            # Espera pelo download do arquivo e renomeia
            caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "NFS-e - Tomados.pdf", intervalo=6)

            # Verifica se o arquivo foi baixado com sucesso
            if os.path.exists(caminho_pdf):
                print("PDF baixado e renomeado com sucesso:", caminho_pdf)

                # Registrar log de sucesso
                includeLogData(
                    nome_thread,
                    f'NFSE - {name_company}',
                    f'PDF de relatório de NFSE escrituradas - Tomador baixado com sucesso.',
                    f'{cnpj_cpf}',
                    'TOMADOS',
                    'info-gradient',
                    'SUCESSO',
                    'success-gradient'
                )
            else:
                print("Erro: O PDF não foi baixado.")
                includeLogData(
                    nome_thread,
                    f'NFSE - {name_company}',
                    f"Erro: O PDF não foi baixado.",
                    f'{cnpj_cpf}',
                    'TOMADOS',
                    'info-gradient',
                    'ATENÇÃO',
                    'warning-gradient'
                )
        else:
            print("Dropdown de tipo de escrituração não está habilitado.")
    except Exception as e:
        print(f"Erro geral na execução do PDF: {e}")


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
    actions = ActionChains(driver)
    mes = int(execMes)
    ano = int(execAno)

    try:
        # URL do relatório
        prestados_relatorio2 = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/relatorios/notasescrituradas'
        driver.get(prestados_relatorio2)

        # Espera pelo dropdown de tipo de escrituração
        ng_select = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//ng-select[@formcontrolname="tipo_escrituracao"]'))
        )

        if ng_select.is_enabled():
            ng_select.click()
            sleep(5)

            # Seleciona a opção "Fiscal (Serviço Prestado)"
            opcao_fiscal = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH,
                                            '//div[contains(@class, "ng-option") and contains(.//span, "Fiscal (Serviço Prestado)")]'))
            )
            opcao_fiscal.click()

            # Preenche os campos necessários
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{mes}/{ano}").perform()
            sleep(0.5)
            actions.send_keys(Keys.TAB).perform()
            sleep(0.3)
            actions.send_keys(f"{mes}/{ano}").perform()
            actions.send_keys(Keys.TAB).perform()
            sleep(0.5)
            actions.send_keys(f"{cnpj_cpf}").perform()

            # Espera que a lista de resultados apareça
            WebDriverWait(driver, 2).until(
                EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
            )
            sleep(2)
            primeiraOpcao = WebDriverWait(driver, 1).until(
                EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
            )
            primeiraOpcao.click()  # Clica na primeira opção

            # Clica no botão "Imprimir"
            imprimir_relatorio = driver.find_element(By.XPATH,
                                                     '//button[contains(@class, "btn-success") and contains(., "Imprimir")]')
            imprimir_relatorio.click()  # Clica no botão de imprimir

            # Espera pelo download do arquivo e renomeia
            caminho_pdf = esperar_e_renomear_arquivo(pastaArquivos, "NFS-e - Prestados.pdf", intervalo=5)

            # Verifica se o arquivo foi baixado com sucesso
            if os.path.exists(caminho_pdf):
                print("PDF baixado e renomeado com sucesso:", caminho_pdf)

                # Registrar log de sucesso
                includeLogData(
                    nome_thread,
                    f'NFSE - {name_company}',
                    f'PDF de relatório de NFSE escrituradas - Prestador baixado com sucesso.',
                    f'{cnpj_cpf}',
                    'PRESTADOS',
                    'info-gradient',
                    'SUCESSO',
                    'success-gradient'
                )
            else:
                print("Erro: O PDF não foi baixado.")
                includeLogData(
                    nome_thread,
                    f'NFSE - {name_company}',
                    f"Erro: O PDF não foi baixado.",
                    f'{cnpj_cpf}',
                    'PRESTADOS',
                    'info-gradient',
                    'ATENÇÃO',
                    'warning-gradient'
                )
        else:
            print("Dropdown de tipo de escrituração não está habilitado.")
    except Exception as e:
        print(f"Erro geral na execução do PDF: {e}")
        includeLogData(
            nome_thread,
            f'NFSE - {name_company}',
            f'Erro geral na execução do PDF: {e}',
            f'{cnpj_cpf}',
            'PRESTADOS',
            'info-gradient',
            'ATENÇÃO',
            'warning-gradient'
        )

        # Salvar captura de tela em caso de erro
        driver.execute_script("document.body.style.zoom = '75%'")
        pasta_destino = f"{pastaArquivos}/ERRO PDF NFSE PRESTADO.png"
        if os.path.exists(pasta_destino):
            os.remove(pasta_destino)
        driver.save_screenshot(pasta_destino)
        driver.execute_script("document.body.style.zoom = '100%'")
        limpar_pasta(pastaArquivos)

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
 # ========== FUNÇÕES AUXILIARES INTERNAS ==========

 def configurar_filtro_inicial():
  """Configura o filtro inicial da página"""
  ng_select = WebDriverWait(driver, 9).until(
   EC.presence_of_element_located((By.XPATH, "//ng-select"))
  )
  ng_select.click()

 def selecionar_empresa():
  """Seleciona a empresa pelo CNPJ"""
  campoEntrada = WebDriverWait(driver, 2).until(
   EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
  )
  campoEntrada.send_keys(cnpj_cpf)

  WebDriverWait(driver, 2).until(
   EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
  )
  sleep(5)

  primeiraOpcao = WebDriverWait(driver, 1).until(
   EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
  )
  primeiraOpcao.click()

 def preencher_competencia():
  """Preenche a competência (mês/ano)"""
  campoData = WebDriverWait(driver, 1).until(
   EC.presence_of_element_located((By.XPATH, '//input[@formcontrolname="competencia"]'))
  )
  campoData.click()
  campoData.clear()
  campoData.send_keys(f"{mes}/{ano}")
  campoData.send_keys(Keys.TAB)
  sleep(3)

 def verificar_registros_encontrados():
  """Verifica se há registros. Retorna True se houver, False caso contrário"""
  try:
   driver.find_element(By.XPATH, "//h6[contains(text(), 'Nenhum registro encontrado')]")
   return False
  except NoSuchElementException:
   return True

 def configurar_paginacao():
  """Configura paginação para 100 itens"""
  selectQuantidade = WebDriverWait(driver, 5).until(
   EC.presence_of_element_located((By.ID, 'pagination'))
  )
  select = Select(selectQuantidade)
  select.select_by_visible_text('100')

  driver.execute_script("window.scrollTo(0, 0);")
  sleep(2)

 def desmarcar_notas_canceladas():
  """Desmarca checkboxes de notas canceladas na página atual"""
  try:
   linhas_canceladas = driver.find_elements(By.XPATH, '//tr[.//strong[contains(text(), "Cancelada")]]')
   total_canceladas = len(linhas_canceladas)

   if total_canceladas > 0:
    print(f"  🔍 Encontradas {total_canceladas} notas CANCELADAS nesta página")

    for idx, linha in enumerate(linhas_canceladas, 1):
     try:
      checkbox = linha.find_element(By.XPATH, './/input[@type="checkbox"]')
      if checkbox.is_selected():
       driver.execute_script("arguments[0].click();", checkbox)
       print(f"    ❌ Nota cancelada {idx}/{total_canceladas} desmarcada")
       sleep(0.3)
      else:
       print(f"    ⚪ Nota cancelada {idx}/{total_canceladas} já estava desmarcada")
     except Exception as e:
      print(f"    ⚠️ Erro ao desmarcar nota cancelada {idx}: {e}")
   else:
    print("  ✅ Nenhuma nota cancelada encontrada nesta página")
  except Exception as e:
   print(f"  ⚠️ Erro ao buscar notas canceladas: {e}")

 def marcar_todos_checkboxes():
  """Marca todos os checkboxes e depois desmarca os cancelados em todas as páginas"""

  print("\n" + "=" * 60)
  print("PROCESSANDO PRIMEIRA PÁGINA")
  print("=" * 60)

  WebDriverWait(driver, 10).until(
   EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
  )

  driver.execute_script("window.scrollTo(0, 0);")
  sleep(1)

  driver.execute_script("document.querySelector('thead .form-check-input').click();")
  sleep(1)
  print("✅ Todos os checkboxes marcados")

  desmarcar_notas_canceladas()

  pagina_atual = 1
  max_paginas = 50

  while pagina_atual < max_paginas:
   try:
    print("\n" + "=" * 60)
    print(f"INDO PARA PÁGINA {pagina_atual + 1}")
    print("=" * 60)

    sleep(1)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    sleep(0.5)

    botoes_next = driver.find_elements(By.XPATH, '//a[@aria-label="Next"]')
    if not botoes_next:
     print("❌ Botão Next não encontrado - fim da paginação")
     break

    botao_next = botoes_next[0]
    li_parent = botao_next.find_element(By.XPATH, '..')
    classes_li = li_parent.get_attribute('class') or ''

    if 'disabled' in classes_li.lower():
     print("🛑 Última página alcançada (botão desabilitado)")
     break

    if not botao_next.is_displayed():
     print("❌ Botão Next não está visível")
     break

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_next)
    sleep(0.5)
    driver.execute_script("arguments[0].click();", botao_next)
    print("➡️ Clique no Next executado")

    sleep(3)

    WebDriverWait(driver, 10).until(
     EC.presence_of_element_located((By.TAG_NAME, 'thead'))
    )

    driver.execute_script("window.scrollTo(0, 0);")
    sleep(1)

    print(f"☑️ Marcando checkboxes da página {pagina_atual + 1}...")

    is_checked_inicial = driver.execute_script(
     "return document.querySelector('thead .form-check-input').checked;"
    )
    print(f"  - Estado inicial: {is_checked_inicial}")

    if is_checked_inicial:
     print("  - Checkbox já marcado, fazendo toggle...")
     driver.execute_script("document.querySelector('thead .form-check-input').click();")
     sleep(0.5)
     driver.execute_script("document.querySelector('thead .form-check-input').click();")
     sleep(0.5)
    else:
     print("  - Checkbox desmarcado, marcando...")
     driver.execute_script("document.querySelector('thead .form-check-input').click();")
     sleep(0.5)

    is_checked_final = driver.execute_script(
     "return document.querySelector('thead .form-check-input').checked;"
    )
    print(f"✅ Todos marcados: {is_checked_final}")

    desmarcar_notas_canceladas()
    pagina_atual += 1

   except Exception as e:
    print(f"❌ ERRO: {e}")
    import traceback
    traceback.print_exc()
    break

  print("\n" + "=" * 60)
  print(f"✅ TOTAL DE PÁGINAS PROCESSADAS: {pagina_atual}")
  print("=" * 60 + "\n")

 def baixar_xml(pasta_destino_xml):
  """Faz o download dos XMLs selecionados"""
  max_tentativas = 3
  tentativa_atual = 0

  while tentativa_atual < max_tentativas:
   try:
    if len(driver.window_handles) > 1:
     main_window = driver.window_handles[0]
     for handle in driver.window_handles[1:]:
      driver.switch_to.window(handle)
      driver.close()
     driver.switch_to.window(main_window)

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    sleep(1)
    driver.execute_script("window.scrollTo(0, 0);")
    sleep(1)

    baixar_xml_btn = WebDriverWait(driver, 10).until(
     EC.presence_of_element_located((By.XPATH,
                                     '//button[contains(@class, "btn-success") and contains(., "XML Seleção")]'))
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", baixar_xml_btn)
    sleep(1)
    driver.execute_script("arguments[0].click();", baixar_xml_btn)
    sleep(3)

    if '{"code":2,"error":"Undefined array key 1"}' in driver.page_source:
     print("Erro detectado: 'Undefined array key 1'. Tentando novamente...")
     tentativa_atual += 1
     if tentativa_atual < max_tentativas:
      refazer_busca()
      continue
     else:
      break

    arquivos_crdownload = [f for f in os.listdir(pastaArquivos) if f.endswith('.crdownload')]
    if arquivos_crdownload:
     print(f"Arquivo .crdownload detectado - Tentativa {tentativa_atual + 1}")
     for arquivo in arquivos_crdownload:
      try:
       os.remove(os.path.join(pastaArquivos, arquivo))
      except:
       pass
     tentativa_atual += 1
     if tentativa_atual < max_tentativas:
      sleep(3)
      continue
     else:
      break

    if aguardar_download_zip():
     processar_zip_e_mover_xmls(pasta_destino_xml)
     return True
    else:
     tentativa_atual += 1

   except Exception as e:
    print(f"Erro na tentativa {tentativa_atual + 1}: {e}")
    tentativa_atual += 1
    if tentativa_atual < max_tentativas:
     sleep(3)

  return False

 def aguardar_download_zip():
  """Aguarda o download do arquivo ZIP"""
  downloaded = False
  timeout_download = 60
  start_time = time.time()

  while not downloaded and (time.time() - start_time) < timeout_download:
   NomeParcial = 'NFS'
   arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
   for arquivo in arquivos_zip:
    if NomeParcial in os.path.basename(arquivo):
     if verify_downloaded(arquivo):
      downloaded = True
      print(f"Download reconhecido: {arquivo}")
      break
   if not downloaded:
    sleep(1)

  return downloaded

 def processar_zip_e_mover_xmls(pasta_destino_xml):
  """
  Extrai ZIP(s) e move XML(s) para pasta específica.
  Correção: não filtra ZIP por '.xml' no nome; extrai todos os ZIPs baixados.
  """
  os.makedirs(pasta_destino_xml, exist_ok=True)

  arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
  if not arquivos_zip:
   print("⚠️ Nenhum ZIP encontrado para extrair.")
   return

  for arquivo_zip in arquivos_zip:
   try:
    with zipfile.ZipFile(arquivo_zip, 'r') as z:
     z.extractall(path=pastaArquivos)
    print(f"✅ ZIP extraído: {arquivo_zip}")
   except zipfile.BadZipFile:
    print(f"❌ ZIP corrompido: {arquivo_zip}")
    continue
   except Exception as e:
    print(f"❌ Erro ao extrair ZIP {arquivo_zip}: {e}")
    continue

  xmls_encontrados = []
  for nome in os.listdir(pastaArquivos):
   caminho = os.path.join(pastaArquivos, nome)
   if os.path.isfile(caminho) and nome.lower().endswith('.xml'):
    xmls_encontrados.append(caminho)

  if not xmls_encontrados:
   print("⚠️ Nenhum XML encontrado após extração.")
   try:
    print("Arquivos na pasta após extração:", os.listdir(pastaArquivos)[:80])
   except:
    pass
  else:
   for caminho_xml in xmls_encontrados:
    nome_xml = os.path.basename(caminho_xml)
    destino_xml = os.path.join(pasta_destino_xml, nome_xml)
    try:
     if os.path.exists(destino_xml):
      try:
       os.remove(destino_xml)
      except:
       pass
     shutil.move(caminho_xml, destino_xml)
     print(f"✅ XML movido: {nome_xml}")
    except Exception as e:
     print(f"❌ Erro ao mover XML {nome_xml}: {e}")

  for arquivo_zip in arquivos_zip:
   try:
    os.remove(arquivo_zip)
   except:
    pass

 # =================== HELPERS (PDF: IMPRIMIR COMO PDF VIA CDP) ===================

 def _fechar_abas_extras():
  """Garante apenas a aba principal aberta."""
  if len(driver.window_handles) > 1:
   main_window = driver.window_handles[0]
   for handle in driver.window_handles[1:]:
    driver.switch_to.window(handle)
    driver.close()
   driver.switch_to.window(main_window)

 def _esperar_nova_aba(handles_antes, timeout=25):
  """Espera abrir uma nova aba e retorna o handle novo."""
  fim = time.time() + timeout
  while time.time() < fim:
   handles_agora = driver.window_handles
   if len(handles_agora) > len(handles_antes):
    novos = [h for h in handles_agora if h not in handles_antes]
    if novos:
     return novos[0]
   sleep(0.2)
  return None

 def _salvar_pdf_cdp_print(caminho_saida):
  """
  Gera PDF da página atual usando Chrome DevTools (Page.printToPDF).
  Funciona mesmo quando a aba abre HTML (DANFSE) e não um PDF nativo.
  """
  import base64

  # aguarda o carregamento
  try:
   WebDriverWait(driver, 20).until(
    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
   )
  except:
   pass

  # dá tempo para renderizar conteúdo via JS
  sleep(1.5)
  try:
   for _ in range(12):
    txt_len = driver.execute_script("return (document.body && document.body.innerText || '').length;")
    if txt_len and int(txt_len) > 50:
     break
    sleep(0.5)
  except:
   pass

  result = driver.execute_cdp_cmd("Page.printToPDF", {
   "printBackground": True,
   "landscape": False,
   "preferCSSPageSize": True,
   "scale": 1
  })

  data = result.get("data")
  if not data:
   raise Exception("CDP Page.printToPDF não retornou 'data'.")

  pdf_bytes = base64.b64decode(data)
  if not pdf_bytes.startswith(b"%PDF"):
   raise Exception("CDP gerou saída que não parece PDF (não inicia com %PDF).")

  os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
  with open(caminho_saida, "wb") as f:
   f.write(pdf_bytes)

  return caminho_saida

 def baixar_pdf(nome_pdf):
  """
  Clique em 'Imprimir Seleção' abre nova aba (HTML do DANFSE).
  Aqui a gente imprime a página para PDF via CDP e salva no disco.
  """
  max_tentativas_pdf = 3

  for tentativa_pdf in range(1, max_tentativas_pdf + 1):
   try:
    _fechar_abas_extras()

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    sleep(1)
    driver.execute_script("window.scrollTo(0, 0);")
    sleep(1)

    imprimir_notas = WebDriverWait(driver, 10).until(
     EC.element_to_be_clickable((By.XPATH,
                                 '//button[contains(@class, "btn-success") and contains(., "Imprimir Seleção")]'))
    )

    handles_antes = driver.window_handles[:]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", imprimir_notas)
    sleep(0.5)
    driver.execute_script("arguments[0].click();", imprimir_notas)

    handle_pdf = _esperar_nova_aba(handles_antes, timeout=25)
    if not handle_pdf:
     print(f"⚠️ Tentativa {tentativa_pdf}: não abriu nova aba do DANFSE.")
     continue

    driver.switch_to.window(handle_pdf)
    WebDriverWait(driver, 20).until(lambda d: d.current_url and len(d.current_url) > 10)

    url = driver.current_url
    print(f"🔗 URL do DANFSE capturada: {url}")

    caminho_saida = os.path.join(pastaArquivos, nome_pdf)
    if os.path.exists(caminho_saida):
     try:
      os.remove(caminho_saida)
     except:
      pass

    _salvar_pdf_cdp_print(caminho_saida)

    driver.close()
    driver.switch_to.window(driver.window_handles[0])

    if os.path.exists(caminho_saida) and os.path.getsize(caminho_saida) > 0:
     print(f"✅ PDF gerado via impressão: {caminho_saida}")
     return caminho_saida

    print(f"⚠️ Tentativa {tentativa_pdf}: arquivo não apareceu/está vazio.")
    sleep(2)

   except Exception as e:
    print(f"Erro ao gerar PDF (tentativa {tentativa_pdf}): {e}")
    try:
     if len(driver.window_handles) > 1:
      driver.switch_to.window(driver.window_handles[-1])
      driver.close()
     driver.switch_to.window(driver.window_handles[0])
    except:
     pass
    sleep(2)

  return None

 def refazer_busca():
  """Recarrega a página e refaz toda a busca"""
  driver.get(xml_tomados)
  sleep(3)

  configurar_filtro_inicial()
  selecionar_empresa()
  preencher_competencia()
  configurar_paginacao()
  driver.execute_script("window.scrollTo(0, 0);")
  sleep(2)
  marcar_todos_checkboxes()

 def capturar_screenshot_erro():
  """Captura screenshot em caso de erro"""
  try:
   driver.execute_script("document.body.style.zoom = '75%'")
   pasta_destino = f"{pastaArquivos}/ERRO_NFSE_TOMADOS.png"
   if os.path.exists(pasta_destino):
    os.remove(pasta_destino)
   driver.save_screenshot(pasta_destino)
   driver.execute_script("document.body.style.zoom = '100%'")
  except:
   pass

 # ========== INÍCIO DA FUNÇÃO PRINCIPAL ==========

 actions = ActionChains(driver)
 mes = int(execMes)
 ano = int(execAno)

 includeLogData(nome_thread, f'NFSE - {name_company}',
                f'Iniciando processo de download de NFSe de serviços Tomados.',
                f'{cnpj_cpf}', 'TOMADOS', 'info-gradient',
                'SUCESSO', 'success-gradient')

 pasta_xml_tomados = os.path.join(pastaArquivos, 'XML - Tomados')
 if not os.path.exists(pasta_xml_tomados):
  os.makedirs(pasta_xml_tomados)
  print(f"Pasta criada: {pasta_xml_tomados}")

 try:
  xml_tomados = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/notasubstitutiva'
  driver.get(xml_tomados)
  sleep(2)

  configurar_filtro_inicial()
  selecionar_empresa()
  preencher_competencia()

  if not verificar_registros_encontrados():
   print("Nenhum registro encontrado.")
   if os.path.exists(pasta_xml_tomados):
    os.rmdir(pasta_xml_tomados)
    print(f"Pasta '{pasta_xml_tomados}' removida.")

   includeLogData(nome_thread, f'NFSE - {name_company}',
                  f'Nenhum registro encontrado para o período.',
                  f'{cnpj_cpf}', 'TOMADOS', 'info-gradient',
                  'ATENÇÃO', 'warning-gradient')
   return

  print("Registros encontrados, prosseguindo...")

  configurar_paginacao()
  marcar_todos_checkboxes()

  driver.execute_cdp_cmd('Page.setDownloadBehavior',
                         {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

  xml_sucesso = baixar_xml(pasta_xml_tomados)
  caminho_pdf = baixar_pdf("NOTAS - Tomados.pdf")

  if caminho_pdf and os.path.exists(caminho_pdf):
   includeLogData(nome_thread, f'NFSE - {name_company}',
                  f'PDF e XML de NFS-E Tomados baixados com sucesso.',
                  f'{cnpj_cpf}', 'TOMADOS', 'info-gradient',
                  'SUCESSO', 'success-gradient')
  else:
   includeLogData(nome_thread, f'NFSE - {name_company}',
                  f"Erro: O PDF não foi baixado.",
                  f'{cnpj_cpf}', 'TOMADOS', 'info-gradient',
                  'ATENÇÃO', 'warning-gradient')

  if os.path.exists(pasta_xml_tomados) and not os.listdir(pasta_xml_tomados):
   os.rmdir(pasta_xml_tomados)
   print(f"Pasta XML vazia removida: {pasta_xml_tomados}")

 except Exception as e:
  print(f"Erro geral na execução: {e}")
  capturar_screenshot_erro()

  includeLogData(nome_thread, f'NFSE - {name_company}',
                 f'Erro na execução: {str(e)}', f'{cnpj_cpf}',
                 'TOMADOS', 'info-gradient', 'ERRO', 'danger-gradient')

def exec_NFSE_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
 # ========== FUNÇÕES AUXILIARES INTERNAS ==========

 def configurar_filtro_inicial():
  """Configura o filtro inicial da página"""
  ng_select = WebDriverWait(driver, 9).until(
   EC.presence_of_element_located((By.XPATH, "//ng-select"))
  )
  ng_select.click()

  el = WebDriverWait(driver, 10).until(
   EC.element_to_be_clickable((By.CSS_SELECTOR, "i.far.fa-filter"))
  )
  driver.execute_script("arguments[0].click();", el)

 def selecionar_empresa():
  """Seleciona a empresa pelo CNPJ"""
  campoEntrada = WebDriverWait(driver, 2).until(
   EC.presence_of_element_located((By.XPATH, "//ng-select//input"))
  )
  campoEntrada.send_keys(cnpj_cpf)

  WebDriverWait(driver, 2).until(
   EC.visibility_of_element_located((By.XPATH, '//ng-dropdown-panel'))
  )
  sleep(4)

  primeiraOpcao = WebDriverWait(driver, 1).until(
   EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
  )
  primeiraOpcao.click()

 def preencher_datas():
  """Preenche as datas inicial e final"""
  campoDatainicial = WebDriverWait(driver, 1).until(
   EC.presence_of_element_located((By.XPATH, '//input[@formcontrolname="nfse_data_inicial"]'))
  )
  campoDatainicial.click()
  campoDatainicial.clear()
  campoDatainicial.send_keys(f"01/{mes}/{ano}")
  campoDatainicial.send_keys(Keys.TAB)
  sleep(0.5)

  campoDatafinal = WebDriverWait(driver, 1).until(
   EC.presence_of_element_located((By.XPATH, '//input[@formcontrolname="nfse_data_final"]'))
  )
  campoDatafinal.click()
  campoDatafinal.clear()
  campoDatafinal.send_keys(f"{ultimo_dia}/{mes}/{ano}")
  campoDatafinal.send_keys(Keys.TAB)
  sleep(3)

 def selecionar_tipo_nota(tipo_nota):
  """Seleciona o tipo de nota (CANCELADA ou EMITIDA)"""
  for _ in range(7):
   actions.send_keys(Keys.TAB)
  actions.perform()

  actions.send_keys(tipo_nota).perform()
  sleep(1)

  primeiraOpcao = WebDriverWait(driver, 1).until(
   EC.element_to_be_clickable((By.XPATH, '//ng-dropdown-panel//div[contains(@class, "ng-option")]'))
  )
  primeiraOpcao.click()

 def verificar_registros_encontrados():
  """Verifica se há registros. Retorna True se houver, False caso contrário"""
  try:
   driver.find_element(By.XPATH, "//h6[contains(text(), 'Nenhum registro encontrado')]")
   return False
  except NoSuchElementException:
   return True

 def configurar_paginacao():
  """Configura paginação para 100 itens"""
  selectQuantidade = WebDriverWait(driver, 5).until(
   EC.presence_of_element_located((By.ID, 'pagination'))
  )
  select = Select(selectQuantidade)
  select.select_by_visible_text('100')

  driver.execute_script("window.scrollTo(0, 0);")
  sleep(2)

 def marcar_todos_checkboxes():
  """Marca todos os checkboxes em todas as páginas"""

  print("\n" + "=" * 60)
  print("MARCANDO CHECKBOXES DA PRIMEIRA PÁGINA")
  print("=" * 60)

  WebDriverWait(driver, 10).until(
   EC.visibility_of_element_located((By.TAG_NAME, 'thead'))
  )

  driver.execute_script("window.scrollTo(0, 0);")
  sleep(1)

  driver.execute_script("document.querySelector('thead .form-check-input').click();")
  sleep(1)
  print("✅ Checkbox da primeira página marcado")

  pagina_atual = 1
  max_paginas = 50

  while pagina_atual < max_paginas:
   try:
    print("\n" + "=" * 60)
    print(f"INDO PARA PÁGINA {pagina_atual + 1}")
    print("=" * 60)

    sleep(1)

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    sleep(0.5)

    botoes_next = driver.find_elements(By.XPATH, '//a[@aria-label="Next"]')
    if not botoes_next:
     print("❌ Botão Next não encontrado - fim da paginação")
     break

    botao_next = botoes_next[0]
    li_parent = botao_next.find_element(By.XPATH, '..')
    classes_li = li_parent.get_attribute('class') or ''

    if 'disabled' in classes_li.lower():
     print("🛑 Última página alcançada (botão desabilitado)")
     break

    if not botao_next.is_displayed():
     print("❌ Botão Next não está visível")
     break

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", botao_next)
    sleep(0.5)
    driver.execute_script("arguments[0].click();", botao_next)
    print("➡️ Clique no Next executado")

    sleep(3)

    WebDriverWait(driver, 10).until(
     EC.presence_of_element_located((By.TAG_NAME, 'thead'))
    )

    driver.execute_script("window.scrollTo(0, 0);")
    sleep(1)

    print(f"☑️ Marcando checkboxes da página {pagina_atual + 1}...")

    is_checked_inicial = driver.execute_script(
     "return document.querySelector('thead .form-check-input').checked;"
    )
    print(f"  - Estado inicial: {is_checked_inicial}")

    if is_checked_inicial:
     print("  - Checkbox já marcado, fazendo toggle...")
     driver.execute_script("document.querySelector('thead .form-check-input').click();")
     sleep(0.5)
     driver.execute_script("document.querySelector('thead .form-check-input').click();")
     sleep(0.5)
    else:
     print("  - Checkbox desmarcado, marcando...")
     driver.execute_script("document.querySelector('thead .form-check-input').click();")
     sleep(0.5)

    is_checked_final = driver.execute_script(
     "return document.querySelector('thead .form-check-input').checked;"
    )
    print(f"✅ Estado final: {is_checked_final}")

    pagina_atual += 1

   except Exception as e:
    print(f"❌ ERRO: {e}")
    import traceback
    traceback.print_exc()
    break

  print("\n" + "=" * 60)
  print(f"✅ TOTAL DE PÁGINAS PROCESSADAS: {pagina_atual}")
  print("=" * 60 + "\n")

 def baixar_xml(pasta_destino_xml):
  """Faz o download dos XMLs selecionados"""
  max_tentativas = 3
  tentativa_atual = 0

  while tentativa_atual < max_tentativas:
   try:
    # Garantir foco na aba principal
    if len(driver.window_handles) > 1:
     main_window = driver.window_handles[0]
     for handle in driver.window_handles[1:]:
      driver.switch_to.window(handle)
      driver.close()
     driver.switch_to.window(main_window)

    # Scroll e clique
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    sleep(1)
    driver.execute_script("window.scrollTo(0, 0);")
    sleep(1)

    baixar_xml_btn = WebDriverWait(driver, 10).until(
     EC.presence_of_element_located((By.XPATH,
                                     '//button[contains(@class, "btn-success") and contains(., "XML Seleção")]'))
    )
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", baixar_xml_btn)
    sleep(1)
    driver.execute_script("arguments[0].click();", baixar_xml_btn)
    sleep(3)

    # Verificar erro específico
    if '{"code":2,"error":"Undefined array key 1"}' in driver.page_source:
     print("Erro detectado: 'Undefined array key 1'. Tentando novamente...")
     tentativa_atual += 1
     if tentativa_atual < max_tentativas:
      refazer_busca()
      continue
     else:
      break

    # Verificar .crdownload
    arquivos_crdownload = [f for f in os.listdir(pastaArquivos) if f.endswith('.crdownload')]
    if arquivos_crdownload:
     print(f"Arquivo .crdownload detectado - Tentativa {tentativa_atual + 1}")
     for arquivo in arquivos_crdownload:
      try:
       os.remove(os.path.join(pastaArquivos, arquivo))
      except:
       pass
     tentativa_atual += 1
     if tentativa_atual < max_tentativas:
      sleep(3)
      continue
     else:
      break

    if aguardar_download_zip():
     processar_zip_e_mover_xmls(pasta_destino_xml)
     return True
    else:
     tentativa_atual += 1

   except Exception as e:
    print(f"Erro na tentativa {tentativa_atual + 1}: {e}")
    tentativa_atual += 1
    if tentativa_atual < max_tentativas:
     sleep(3)

  return False

 def aguardar_download_zip():
  """Aguarda o download do arquivo ZIP"""
  downloaded = False
  timeout_download = 60
  start_time = time.time()

  while not downloaded and (time.time() - start_time) < timeout_download:
   nome_parcial = 'NFS'
   arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
   for arquivo in arquivos_zip:
    if nome_parcial in os.path.basename(arquivo):
     if verify_downloaded(arquivo):
      downloaded = True
      print(f"Download reconhecido: {arquivo}")
      break
   if not downloaded:
    sleep(1)

  return downloaded

 def processar_zip_e_mover_xmls(pasta_destino_xml):
  """
  Extrai ZIP(s) e move XML(s) para pasta específica.
  Ajuste alinhado com TOMADOS: extrai todos os ZIPs e move todos os .xml encontrados.
  """
  os.makedirs(pasta_destino_xml, exist_ok=True)

  arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
  if not arquivos_zip:
   print("⚠️ Nenhum ZIP encontrado para extrair.")
   return

  # 1) Extrair todos os ZIPs
  for arquivo_zip in arquivos_zip:
   try:
    with zipfile.ZipFile(arquivo_zip, 'r') as z:
     z.extractall(path=pastaArquivos)
    print(f"✅ ZIP extraído: {arquivo_zip}")
   except zipfile.BadZipFile:
    print(f"❌ ZIP corrompido: {arquivo_zip}")
    continue
   except Exception as e:
    print(f"❌ Erro ao extrair ZIP {arquivo_zip}: {e}")
    continue

  # 2) Mover XMLs extraídos
  xmls_encontrados = []
  for nome in os.listdir(pastaArquivos):
   caminho = os.path.join(pastaArquivos, nome)
   if os.path.isfile(caminho) and nome.lower().endswith('.xml'):
    xmls_encontrados.append(caminho)

  if not xmls_encontrados:
   print("⚠️ Nenhum XML encontrado após extração.")
   try:
    print("Arquivos na pasta após extração:", os.listdir(pastaArquivos)[:80])
   except:
    pass
  else:
   for caminho_xml in xmls_encontrados:
    nome_xml = os.path.basename(caminho_xml)

    # Se você FAZ QUESTÃO do rename "últimos 10 chars", descomente abaixo:
    # novo_nome = nome_xml[-10:]
    # destino_xml = os.path.join(pasta_destino_xml, novo_nome)

    destino_xml = os.path.join(pasta_destino_xml, nome_xml)

    try:
     if os.path.exists(destino_xml):
      try:
       os.remove(destino_xml)
      except:
       pass
     shutil.move(caminho_xml, destino_xml)
     print(f"✅ XML movido: {os.path.basename(destino_xml)}")
    except Exception as e:
     print(f"❌ Erro ao mover XML {nome_xml}: {e}")

  # 3) Limpar ZIPs
  for arquivo_zip in arquivos_zip:
   try:
    os.remove(arquivo_zip)
   except:
    pass

 # =================== HELPERS (PDF: IMPRIMIR COMO PDF VIA CDP) ===================

 def _fechar_abas_extras():
  """Garante apenas a aba principal aberta."""
  if len(driver.window_handles) > 1:
   main_window = driver.window_handles[0]
   for handle in driver.window_handles[1:]:
    driver.switch_to.window(handle)
    driver.close()
   driver.switch_to.window(main_window)

 def _esperar_nova_aba(handles_antes, timeout=25):
  """Espera abrir nova aba e retorna o handle novo."""
  fim = time.time() + timeout
  while time.time() < fim:
   handles_agora = driver.window_handles
   if len(handles_agora) > len(handles_antes):
    novos = [h for h in handles_agora if h not in handles_antes]
    if novos:
     return novos[0]
   sleep(0.2)
  return None

 def _salvar_pdf_cdp_print(caminho_saida):
  """
  Gera PDF da página atual usando Chrome DevTools (Page.printToPDF).
  Funciona mesmo quando a aba abre HTML (DANFSE) e não um PDF nativo.
  """
  import base64

  try:
   WebDriverWait(driver, 20).until(
    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
   )
  except:
   pass

  sleep(1.5)
  try:
   for _ in range(12):
    txt_len = driver.execute_script("return (document.body && document.body.innerText || '').length;")
    if txt_len and int(txt_len) > 50:
     break
    sleep(0.5)
  except:
   pass

  result = driver.execute_cdp_cmd("Page.printToPDF", {
   "printBackground": True,
   "landscape": False,
   "preferCSSPageSize": True,
   "scale": 1
  })

  data = result.get("data")
  if not data:
   raise Exception("CDP Page.printToPDF não retornou 'data'.")

  pdf_bytes = base64.b64decode(data)
  if not pdf_bytes.startswith(b"%PDF"):
   raise Exception("CDP gerou saída que não parece PDF (não inicia com %PDF).")

  os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
  with open(caminho_saida, "wb") as f:
   f.write(pdf_bytes)

  return caminho_saida

 def baixar_pdf(nome_pdf):
  """
  Em PRESTADOS, 'Imprimir Seleção' também abre página HTML.
  Aqui a gente imprime a aba para PDF via CDP e salva.
  """
  max_tentativas_pdf = 3

  for tentativa_pdf in range(1, max_tentativas_pdf + 1):
   try:
    _fechar_abas_extras()

    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    sleep(1)
    driver.execute_script("window.scrollTo(0, 0);")
    sleep(1)

    imprimir_notas = WebDriverWait(driver, 10).until(
     EC.element_to_be_clickable((By.XPATH,
                                 '//button[contains(@class, "btn-success") and contains(., "Imprimir Seleção")]'))
    )

    handles_antes = driver.window_handles[:]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", imprimir_notas)
    sleep(0.5)
    driver.execute_script("arguments[0].click();", imprimir_notas)

    handle_pdf = _esperar_nova_aba(handles_antes, timeout=25)
    if not handle_pdf:
     print(f"⚠️ Tentativa {tentativa_pdf}: não abriu nova aba do DANFSE.")
     continue

    driver.switch_to.window(handle_pdf)
    WebDriverWait(driver, 20).until(lambda d: d.current_url and len(d.current_url) > 10)

    url = driver.current_url
    print(f"🔗 URL do DANFSE capturada: {url}")

    caminho_saida = os.path.join(pastaArquivos, nome_pdf)
    if os.path.exists(caminho_saida):
     try:
      os.remove(caminho_saida)
     except:
      pass

    _salvar_pdf_cdp_print(caminho_saida)

    driver.close()
    driver.switch_to.window(driver.window_handles[0])

    if os.path.exists(caminho_saida) and os.path.getsize(caminho_saida) > 0:
     print(f"✅ PDF gerado via impressão: {caminho_saida}")
     return caminho_saida

    print(f"⚠️ Tentativa {tentativa_pdf}: arquivo não apareceu/está vazio.")
    sleep(2)

   except Exception as e:
    print(f"Erro ao gerar PDF (tentativa {tentativa_pdf}): {e}")
    try:
     if len(driver.window_handles) > 1:
      driver.switch_to.window(driver.window_handles[-1])
      driver.close()
     driver.switch_to.window(driver.window_handles[0])
    except:
     pass
    sleep(2)

  return None

 def refazer_busca():
  """Recarrega a página e refaz toda a busca"""
  driver.get(xml_prestadas)
  sleep(3)

  configurar_filtro_inicial()
  selecionar_empresa()
  preencher_datas()
  configurar_paginacao()
  driver.execute_script("window.scrollTo(0, 0);")
  sleep(2)
  marcar_todos_checkboxes()

 def processar_notas(tipo_nota, pasta_xml, nome_pdf):
  """Processa notas de um tipo específico (CANCELADA ou EMITIDA)"""
  print(f"\n{'=' * 60}")
  print(f"Processando notas: {tipo_nota}")
  print(f"{'=' * 60}\n")

  configurar_filtro_inicial()
  selecionar_empresa()
  preencher_datas()
  selecionar_tipo_nota(tipo_nota)

  if not verificar_registros_encontrados():
   print(f"Nenhum registro {tipo_nota} encontrado.")
   try:
    if os.path.exists(pasta_xml) and not os.listdir(pasta_xml):
     os.rmdir(pasta_xml)
     print(f"Pasta '{pasta_xml}' removida (sem registros).")
   except Exception:
    pass

   includeLogData(nome_thread, f'NFSE {tipo_nota} - {name_company}',
                  f'Nenhum registro encontrado para o período.',
                  f'{cnpj_cpf}', 'PRESTADOS', 'info-gradient',
                  'ATENÇÃO', 'warning-gradient')
   return

  print(f"Registros {tipo_nota} encontrados, prosseguindo...")

  configurar_paginacao()
  marcar_todos_checkboxes()

  driver.execute_cdp_cmd('Page.setDownloadBehavior',
                         {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

  _ = baixar_xml(pasta_xml)
  caminho_pdf = baixar_pdf(nome_pdf)

  if caminho_pdf and os.path.exists(caminho_pdf):
   includeLogData(nome_thread, f'NFSE - {name_company}',
                  f'PDF e XML de NFS-E {tipo_nota} baixados com sucesso.',
                  f'{cnpj_cpf}', 'PRESTADOS', 'info-gradient',
                  'SUCESSO', 'success-gradient')
  else:
   includeLogData(nome_thread, f'NFSE - {name_company}',
                  f"Erro: O PDF {tipo_nota} não foi baixado.",
                  f'{cnpj_cpf}', 'PRESTADOS', 'info-gradient',
                  'ATENÇÃO', 'warning-gradient')

  try:
   if os.path.exists(pasta_xml) and not os.listdir(pasta_xml):
    os.rmdir(pasta_xml)
    print(f"Pasta XML vazia removida: {pasta_xml}")
  except Exception:
   pass

 def capturar_screenshot_erro():
  """Captura screenshot em caso de erro"""
  try:
   driver.execute_script("document.body.style.zoom = '75%'")
   pasta_destino = f"{pastaArquivos}/ERRO_NFSE_PRESTADOS.png"
   if os.path.exists(pasta_destino):
    os.remove(pasta_destino)
   driver.save_screenshot(pasta_destino)
   driver.execute_script("document.body.style.zoom = '100%'")
  except:
   pass

 # ========== INÍCIO DA FUNÇÃO PRINCIPAL ==========

 actions = ActionChains(driver)
 mes = int(execMes)
 ano = int(execAno)
 ultimo_dia = calendar.monthrange(ano, mes)[1]

 includeLogData(nome_thread, f'NFSE - {name_company}',
                f'Iniciando processo de download de NFSe de serviços Prestados.',
                f'{cnpj_cpf}', 'PRESTADOS', 'info-gradient',
                'SUCESSO', 'success-gradient')

 pasta_xml_prestados = os.path.join(pastaArquivos, 'XML - Prestados')
 pasta_xml_cancelados = os.path.join(pastaArquivos, 'XML- P. Canceladas')

 for pasta in [pasta_xml_prestados, pasta_xml_cancelados]:
  if not os.path.exists(pasta):
   os.makedirs(pasta)
   print(f"Pasta criada: {pasta}")

 try:
  xml_prestadas = 'https://cidadaoonline.primaveradoleste.mt.gov.br/app/empresas/notaeletronica'
  driver.get(xml_prestadas)
  sleep(2)

  # EMITIDAS
  try:
   processar_notas("EMITIDA", pasta_xml_prestados, "NOTAS - Emitidas.pdf")
  except Exception as e:
   print(f"Falha ao processar EMITIDA: {e}")

  # CANCELADAS
  try:
   driver.refresh()
   sleep(3)
   processar_notas("CANCELADA", pasta_xml_cancelados, "NOTAS - P. Canceladas.pdf")
  except Exception as e:
   print(f"Falha ao processar CANCELADA: {e}")

 except Exception as e:
  print(f"Erro geral na execução: {e}")
  capturar_screenshot_erro()

  includeLogData(nome_thread, f'NFSE - {name_company}',
                 f'Erro na execução: {str(e)}', f'{cnpj_cpf}',
                 'PRESTADOS', 'info-gradient', 'ERRO', 'danger-gradient')