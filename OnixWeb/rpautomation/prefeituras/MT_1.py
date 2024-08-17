import shutil
import threading

import PyPDF2
import pandas as pd
from selenium import webdriver
from selenium.common import NoSuchElementException, ElementNotInteractableException, TimeoutException
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

from OnixWeb.addons.OnixSender import SendRPAData
# from apps.authentication.models import Companies, ReportsRefreshControl, FilesParameters
# from apps.configs.globals import Globals
from OnixWeb.addons.appscontext import *

from OnixWeb.addons.models import PessoaJuridica, logData, ThreadingCounter, PessoaFisica, AgendamentosRPA, Empresas
from OnixWeb.addons.util import log_message, verify_downloaded, limpar_pasta

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


def MainExecution_Juridica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

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
        password = pessoa['password']

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

        '########## INICIA O DRIVER E CONFIGURA PARA CADA EXECUÇÃO ##########'
        driver = IniciarDriver()
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

        '########## REALIZA O LOGIN ###########'
        logado = exec_LOGIN(driver, nome_thread, name_company, username, username, password, pastaArquivos)
        if logado:
            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['enc_taken']:
                exec_ENC_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec)
            if listaParametros['enc_provided']:
                exec_ENC_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec)

            if listaParametros['issqn']:
                exec_GUIAISSQN(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            sleep(1)
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


def MainExecution_Juridica_Padrao(listaPessoas, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPJ(listaPessoas, EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

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
        password = pessoa['password']
        listaParametros = checkParamPadrao('PJ', id_company)

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

        '########## INICIA O DRIVER E CONFIGURA PARA CADA EXECUÇÃO ##########'
        driver = IniciarDriver()
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

        '########## REALIZA O LOGIN ###########'
        logado = exec_LOGIN(driver, nome_thread, name_company, username, username, password, pastaArquivos)
        if logado:
            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            sleep(1)
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


def MainExecution_Fisica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPF(listaPessoas, EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    for pessoa in dados:
        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Iniciando processos para a pessoa física...',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')

        name_company = pessoa['name']
        id_company = pessoa['id']
        username = pessoa['username']
        password = pessoa['password']
        ie = pessoa['ie']

        '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
        anoExec = f'{Ano}'
        if len(str(Mes)) == 1:
            mesExec = f'0{Mes}'
        else:
            mesExec = f'{Mes}'

        '########## VERIFICA PASTA TEMPORARIA ##########'
        nome_empresa = f"{name_company} - {ie}"
        pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
        if not os.path.exists(pastaArquivos):
            os.makedirs(pastaArquivos)

        '########## INICIA O DRIVER E CONFIGURA PARA CADA EXECUÇÃO ##########'
        driver = IniciarDriver()
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

        '########## REALIZA O LOGIN ###########'
        logado = exec_LOGIN(driver, nome_thread, name_company, username, username, password, pastaArquivos)
        if logado:
            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['enc_taken']:
                exec_ENC_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec)
            if listaParametros['enc_provided']:
                exec_ENC_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec)

            if listaParametros['issqn']:
                exec_GUIAISSQN(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            sleep(1)
            limpar_pasta(pastaArquivos)

        '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Processos finalizados para a pessoa física...',
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


def MainExecution_Fisica_Padrao(listaPessoas, EmpresaExec, Ano, Mes):
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPF(listaPessoas, EmpresaExec)
    listaLen = len(listaPessoas)
    percentilProcesso = 80
    percentilPorPessoa = int(percentilProcesso / listaLen)
    percentilInicial = 5
    setPercentilProcesso(nome_thread, percentilInicial)

    for pessoa in dados:
        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Iniciando processos para a pessoa física...',
                       'BOT',
                       'BOT',
                       'primary-gradient',
                       'SUCESSO',
                       'success-gradient')

        name_company = pessoa['name']
        id_company = pessoa['id']
        username = pessoa['username']
        password = pessoa['password']
        ie = pessoa['ie']
        listaParametros = checkParamPadrao('PF', id_company)

        '########### DADOS DE ANO E MES DA EXECUÇÃO ###########'
        anoExec = f'{Ano}'
        if len(str(Mes)) == 1:
            mesExec = f'0{Mes}'
        else:
            mesExec = f'{Mes}'

        '########## VERIFICA PASTA TEMPORARIA ##########'
        nome_empresa = f"{name_company} - {ie}"
        pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
        if not os.path.exists(pastaArquivos):
            os.makedirs(pastaArquivos)

        '########## INICIA O DRIVER E CONFIGURA PARA CADA EXECUÇÃO ##########'
        driver = IniciarDriver()
        driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

        '########## REALIZA O LOGIN ###########'
        logado = exec_LOGIN(driver, nome_thread, name_company, username, username, password, pastaArquivos)
        if logado:
            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['taken']:
                exec_PDF_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['provided']:
                exec_PDF_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                exec_XML_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            if listaParametros['nfe_taken']:
                exec_NFSE_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
            if listaParametros['nfe_provided']:
                exec_NFSE_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

            sleep(1)
            limpar_pasta(pastaArquivos)

        '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

        includeLogData(nome_thread,
                       f'PROCESSOS - {pessoa["name"]}',
                       'Processos finalizados para a pessoa física...',
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


def MainExecution_Agendamentos(idAgendamento, idCidade):
    with app.app_context():
        dadosAgendamento = AgendamentosRPA.query.filter_by(id=idAgendamento).first()
        dadosAgendamento.status = 'Em Execução'
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
            password = pessoa['password']
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

            nome_empresa = ''
            '########## VERIFICA PASTA TEMPORARIA ##########'
            if dadosAgendamento.tipo_pessoa_agendamento == 'PJ':
                nome_empresa = f"{name_company} - {username}"
            elif dadosAgendamento.tipo_pessoa_agendamento == 'PF':
                nome_empresa = f"{name_company} - {ie}"

            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            '########## INICIA O DRIVER E CONFIGURA PARA CADA EXECUÇÃO ##########'
            driver = IniciarDriver()
            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '########## REALIZA O LOGIN ###########'
            logado = exec_LOGIN(driver, nome_thread, name_company, username, username, password, pastaArquivos)
            if logado:
                '######### EXECUTA ESCOLHAS APOS LOGADO ########'
                if listaParametros['enc_taken'] and 'pref_enc_tomado' in ParametrosAgendamento:
                    exec_ENC_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec)
                if listaParametros['enc_provided'] and 'pref_enc_prestado' in ParametrosAgendamento:
                    exec_ENC_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec)

                if listaParametros['issqn'] and 'pref_guia_issqn' in ParametrosAgendamento:
                    exec_GUIAISSQN(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

                if listaParametros['taken'] and 'pref_rel_tomado' in ParametrosAgendamento:
                    exec_PDF_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                    exec_XML_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                if listaParametros['provided'] and 'pref_rel_prestado' in ParametrosAgendamento:
                    exec_PDF_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                    exec_XML_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

                if listaParametros['nfe_taken'] and 'pref_nfe_tomado' in ParametrosAgendamento:
                    exec_NFSE_TOMADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)
                if listaParametros['nfe_provided'] and 'pref_nfe_prestado' in ParametrosAgendamento:
                    exec_NFSE_PRESTADOS(driver, nome_thread, name_company, username, mesExec, anoExec, pastaArquivos)

                sleep(1)
                limpar_pasta(pastaArquivos)

            '########## FINALIZA O DRIVER E LOGS/PERCENTIL #########'

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

        '### ENVIA OS ARQUIVOS PARA O SERVIDOR BASE TIPO PESSOA'
        DadosEmpresaEnvio = Empresas.query.filter_by(id=dadosAgendamento.id_empresa).first()
        if DadosEmpresaEnvio.autorizado_schedule:
            pathEnvio = dadosAgendamento.path_receiver
            receiver_ip = DadosEmpresaEnvio.receiver_ip
            receiver_port = DadosEmpresaEnvio.receiver_port
            zipData = os.path.join(root_path, fr"OnixWeb\rpautomation\transactionFiles\{nome_thread}.zip")

            print('Iniciando envio para:')
            print(f'IP: {receiver_ip}')
            print(f'Porta: {receiver_port}')
            print(f'zipDataPath: {zipData}')
            print(f'ReceiverPath: {pathEnvio}')
            SendRPAData(dadosAgendamento.id, zipData, receiver_ip, receiver_port, pathEnvio)

            print('Envio Finalizado!')


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
    service = Service(os.path.join(root_path, fr"OnixWeb\rpautomation\dependencias\chromedriver\chromedriver.exe"))
    chrome_options = Options()
    # chrome_options.add_argument('--headless')
    chrome_options.add_argument('--window-size=1080,900')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    prefs = {"plugins.plugins_list": [{"enabled": False,
                                       "name": "Chrome PDF Viewer"}],
             "download.extensions_to_open": "",
             "plugins.always_open_pdf_externally": True,
             "credentials_enable_service": False,
             "profile.password_manager_enabled": False
             }
    chrome_options.add_experimental_option('prefs', prefs)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    # driver.set_page_load_timeout(10)
    return driver


def exec_LOGIN(driver, nome_thread, name_company, cnpj_cpf, username, password, pastaArquivos):
    try:
        login_page = "http://s32.asp.srv.br:8080/issonline/servlet/hlogin"
        try:
            driver.get(login_page)
        except TimeoutException:
            driver.refresh()
        campo_login = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="_USUARIOLOGINLOGIN"]')))
        campo_login.send_keys(username)
        sleep(0.5)
        Entrar = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="TBLOGIN"]/tbody/tr[4]/td/p/a')))
        Entrar.click()
        # campo_login.send_keys(Keys.ENTER)
        try:
            campo_senha = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="_USUARIOLOGINSENHA"]')))
            campo_senha.send_keys(password)
            campo_senha.send_keys(Keys.ENTER)
            sleep(0.5)
        except Exception as Error:
            try:
                erro = driver.find_element(By.XPATH,
                                           '//*[@id="TABLE3"]/tbody/tr[3]/td/span/menu/li').get_attribute(
                    "textContent")
                includeLogData(nome_thread,
                               f'LOGIN - {name_company}',
                               f'Erro ao logar - {erro}.',
                               f'{cnpj_cpf}',
                               'PREFEITURA',
                               'info-gradient',
                               'ATENÇÃO',
                               'warning-gradient')
            except Exception as e:
                includeLogData(nome_thread,
                               f'LOGIN - {name_company}',
                               f'Erro ao logar - Não foi possivel identificar o erro...',
                               f'{cnpj_cpf}',
                               'PREFEITURA',
                               'info-gradient',
                               'ATENÇÃO',
                               'warning-gradient')

            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/ERRO AO LOGAR.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")

            raise Exception(f'{erro}')

        max_attempts = 2
        attempts = 0

        while not driver.find_elements(By.XPATH, '//*[@id="W0004TXBUSUARIO"]'):
            driver.execute_script(f"window.open('{login_page}', 'new_window')")
            sleep(0.2)
            driver.switch_to.window(driver.window_handles[-1])
            sleep(0.2)
            driver.find_element(By.XPATH, '//*[@id="_USUARIOLOGINLOGIN"]').send_keys('username')
            driver.find_element(By.XPATH, '//*[@id="_USUARIOLOGINLOGIN"]').send_keys(Keys.ENTER)
            sleep(1)
            driver.find_element(By.XPATH, '//*[@id="_USUARIOLOGINSENHA"]').send_keys('password')
            driver.find_element(By.XPATH, '//*[@id="_USUARIOLOGINSENHA"]').send_keys(Keys.ENTER)
            attempts += 1
            if attempts == max_attempts:
                ## SALVA PRINT DE SENHA ERRADA/BLOQUEADO AO LOGAR
                driver.execute_script("document.body.style.zoom = '75%'")
                pasta_destino = f"{pastaArquivos}/SENHA INVALIDA-BLOQUEADA.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                driver.execute_script("document.body.style.zoom = '100%'")

                raise Exception('Não foi possível logar após 2 tentativas.')
        else:
            includeLogData(nome_thread,
                           f'LOGIN - {name_company}',
                           f'Login realizado - iniciando processo assinalados...',
                           f'{cnpj_cpf}',
                           'PREFEITURA',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
            return True
    except Exception as Error:
        includeLogData(nome_thread,
                       f'LOGIN - {name_company}',
                       f'Não conseguiu logar - Senha inválida/Máximo de tentativas atingido...',
                       f'{cnpj_cpf}',
                       'PREFEITURA',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
        return False


def exec_PDF_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    try:
        tomados_relatorio2 = 'http://s32.asp.srv.br:8080/issonline/servlet/hrelnotastomadas'
        mes = int(execMes)
        ano = int(execAno)
        try:
            driver.get(f'{tomados_relatorio2}')
        except TimeoutException:
            print(
                f"Timeout ao acessar {tomados_relatorio2} a página. Tentando novamente...")
            driver.refresh()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select'))).click()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]'))).click()

        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        campoTipo = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, f'//*[@id="TABLE1"]/tbody/tr[5]/td[2]/select')))

        selectTipo = Select(campoTipo)
        selectTipo.select_by_visible_text(f"Ambas")
        sleep(0.5)

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, f'//*[@id="IMGIMPRIMIR"]'))).click()
        try:
            driver.switch_to.frame('Embpage')
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="open-button"]'))).click()
        except Exception as e:
            "print('Clicou para baixar Tomados relatorio 2, com except.')"

        pdf = os.path.join(pastaArquivos, 'orelnotastomadas.pdf')
        downloaded = False
        arquivo = pdf
        while not downloaded:
            if verify_downloaded(arquivo) is True:
                downloaded = True
            else:
                downloaded = False

        novo_nome = f'{pastaArquivos}/NFS-e Tomado.pdf'
        if os.path.exists(novo_nome):
            os.remove(novo_nome)

        os.rename(pdf, novo_nome)
        sleep(0.5)
        if os.path.exists(os.path.join(pastaArquivos, 'orelnotastomadas.pdf')):
            os.remove(os.path.join(pastaArquivos, 'orelnotastomadas.pdf'))
        includeLogData(nome_thread,
                       f'PDF - {name_company}',
                       f'PDF dos serviços Tomados baixado com sucesso.',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'SUCESSO',
                       'success-gradient')
    except Exception as e:
        includeLogData(nome_thread,
                       f'PDF - {name_company}',
                       f'Erro ao baixar PDF dos serviços Tomados...',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')


def exec_XML_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    try:
        xml_tomadas = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwminhanotafiscaleletronica'
        mes = int(execMes)
        ano = int(execAno)
        try:
            driver.get(f'{xml_tomadas}')
        except TimeoutException:
            print(
                f"Timeout ao acessar {xml_tomadas} a página. Tentando novamente...")
            driver.refresh()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select'))).click()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]'))).click()

        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        try:
            possuivalores = WebDriverWait(driver, 4).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="GRID1"]/tbody/tr[2]')))
            if possuivalores:
                exportar = WebDriverWait(driver, 4).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="BTNEXPORTAR"]')))
                exportar.click()

                downloaded = False
                while not downloaded:
                    arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                    for arquivo in arquivos_zip:
                        if verify_downloaded(arquivo) is True:
                            downloaded = True
                        else:
                            downloaded = False
                sleep(0.5)
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                for arquivo in arquivos_zip:
                    zip_padrao_ori = os.path.splitext(os.path.basename(arquivo))[0]
                    zip_padrao = (zip_padrao_ori[5:]).strip()
                    with zipfile.ZipFile(arquivo, 'r') as nome_zip:
                        nome_zip.extractall(path=pastaArquivos, pwd=None)
                    nome_xml = f'NFS-e_{zip_padrao}_{mes}-{ano}'
                    caminho_xml = os.path.join(pastaArquivos, nome_xml + '.xml')
                    novo_nome_xml = f"{pastaArquivos}/XML - Tomado.xml"
                    if os.path.exists(novo_nome_xml):
                        os.remove(novo_nome_xml)
                    os.rename(caminho_xml, novo_nome_xml)
                    os.remove(arquivo)

            includeLogData(nome_thread,
                           f'XML - {name_company}',
                           f'XML dos serviços Tomados baixado com sucesso.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')

        except Exception as Error:
            includeLogData(nome_thread,
                           f'XML - {name_company}',
                           f'Empresa não possui XML dos serviços Tomados.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
    except Exception as Error:
        includeLogData(nome_thread,
                       f'XML - {name_company}',
                       f'Erro ao baixar XML dos serviços Tomados.',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')


def exec_PDF_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    try:
        livro_de_servicos = 'http://s32.asp.srv.br:8080/issonline/servlet/hrellivroservico'
        mes = int(execMes)
        ano = int(execAno)

        try:
            driver.get(f'{livro_de_servicos}')
        except TimeoutException:
            print(
                f"Timeout ao acessar {livro_de_servicos} a página. Tentando novamente...")
            driver.refresh()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select'))).click()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]'))).click()
        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        driver.find_element(By.XPATH, '//*[@id="TABLE1"]/tbody/tr[4]/td[2]/select').click()
        driver.find_element(By.XPATH,
                            f'//*[@id="TABLE1"]/tbody/tr[4]/td[2]/select/option[1]').click()
        driver.find_element(By.XPATH,
                            f'//*[@id="TEXTBLOCK1"]').click()
        driver.find_element(By.XPATH, '//*[@id="IMGIMPRIMIR"]').click()
        cnpjbaixado = False
        try:
            driver.find_element(By.XPATH,
                                '//*[@id="TABELAPARAMETOS"]/tbody/tr[1]/td/span/menu/li')
            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/CNPJ BAIXADO.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")
            includeLogData(nome_thread,
                           f'PDF - {name_company}',
                           f'CNPJ da empresa se encontra BAIXADO.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'ATENÇÃO',
                           'warning-gradient')
            cnpjbaixado = True

        except Exception as e:
            cnpjbaixado = False
        if not cnpjbaixado:
            try:
                driver.switch_to.frame('Embpage')
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, '//*[@id="open-button"]'))).click()
            except Exception as e:
                "print('Clicou para baixar Prestados, com except.')"

        if not cnpjbaixado:
            pdf = os.path.join(pastaArquivos, 'orellivroservico.pdf')
            downloaded = False
            arquivo = pdf
            while not downloaded:
                if verify_downloaded(arquivo) is True:
                    downloaded = True
                else:
                    downloaded = False

            novo_nome = f'{pastaArquivos}/NFS-e Prestado.pdf'
            if os.path.exists(novo_nome):
                os.remove(novo_nome)
            sleep(0.5)
            os.rename(pdf, novo_nome)
            if os.path.exists(os.path.join(pastaArquivos, 'orellivroservico.pdf')):
                os.remove(os.path.join(pastaArquivos, 'orellivroservico.pdf'))
            sleep(0.5)
            includeLogData(nome_thread,
                           f'PDF - {name_company}',
                           f'PDF dos serviços Prestados baixado com sucesso..',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
    except Exception as e:
        try:
            AcessoPagina = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="TEXTBLOCK2"]')))
            if 'Não Autorizado!' in AcessoPagina.get_attribute("textContent"):
                print(f'{AcessoPagina.get_attribute("textContent")}')
                driver.execute_script("document.body.style.zoom = '120%'")
                pasta_destino = f"{pastaArquivos}/Sem Acesso - HrelLivroServico.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                driver.execute_script("document.body.style.zoom = '100%'")
                includeLogData(nome_thread,
                               f'PDF - {name_company}',
                               f'Empresa não possui acesso a tela "HrelLivroServico" para download do PDF de serviços prestados...',
                               f'{cnpj_cpf}',
                               'PRESTADOS',
                               'info-gradient',
                               'ERRO',
                               'danger-gradient')
        except Exception as e:
            includeLogData(nome_thread,
                           f'PDF - {name_company}',
                           f'Erro ao baixar PDF de serviços prestados.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'ATENÇÃO',
                           'warning-gradient')


def exec_XML_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    try:
        xml_prestadas = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwnotafiscaleletronica1'
        mes = int(execMes)
        ano = int(execAno)
        try:
            driver.get(f'{xml_prestadas}')
        except TimeoutException:
            print(
                f"Timeout ao acessar {xml_prestadas} a página. Tentando novamente...")
            driver.refresh()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select'))).click()

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]'))).click()

        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        try:
            if driver.find_element(By.XPATH, '//*[@id="GRID1"]/tbody/tr[2]'):
                exportar = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="BTNEXPORTAR"]')))
                exportar.click()

                popuplink = WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="popupFrame"]')))
                relatorio_xml = popuplink.get_attribute(
                    "src")
                try:
                    driver.get(f'{relatorio_xml}')
                except TimeoutException:
                    driver.refresh()
                driver.find_element(By.XPATH,
                                    '//*[@id="TBL3"]/tbody/tr[3]/td/p/input').click()

                downloaded = False
                while not downloaded:
                    arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                    for arquivo in arquivos_zip:
                        if verify_downloaded(arquivo) is True:
                            downloaded = True
                        else:
                            downloaded = False
                sleep(0.5)
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                for arquivo in arquivos_zip:
                    zip_padrao_ori = os.path.splitext(os.path.basename(arquivo))[0]
                    zip_padrao = (zip_padrao_ori[5:]).strip()
                    with zipfile.ZipFile(arquivo, 'r') as nome_zip:
                        nome_zip.extractall(path=pastaArquivos, pwd=None)
                    nome_xml = f'NFS-e_{zip_padrao}_{mes}-{ano}'
                    caminho_xml = os.path.join(pastaArquivos, nome_xml + '.xml')
                    novo_nome_xml = f"{pastaArquivos}/XML - Prestado.xml"
                    if os.path.exists(novo_nome_xml):
                        os.remove(novo_nome_xml)
                    os.rename(caminho_xml, novo_nome_xml)
                    os.remove(arquivo)

                includeLogData(nome_thread,
                               f'XML - {name_company}',
                               f'XML dos serviços Prestados baixado com sucesso.',
                               f'{cnpj_cpf}',
                               'PRESTADOS',
                               'info-gradient',
                               'SUCESSO',
                               'success-gradient')

        except Exception as e:
            includeLogData(nome_thread,
                           f'XML - {name_company}',
                           f'Empresa não possui XML dos serviços Prestados.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
    except Exception as e:
        print(f'#ERRO AO BAIXAR PDF PRESTADO!')
        try:
            AcessoPagina = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="TEXTBLOCK2"]')))
            if 'Não Autorizado!' in AcessoPagina.get_attribute("textContent"):
                print(f'{AcessoPagina.get_attribute("textContent")}')
                driver.execute_script("document.body.style.zoom = '120%'")
                pasta_destino = f"{pastaArquivos}/Sem Acesso - HWWNotaFiscalEletronica1.png"
                if os.path.exists(pasta_destino):
                    os.remove(pasta_destino)
                driver.save_screenshot(pasta_destino)
                driver.execute_script("document.body.style.zoom = '100%'")
                includeLogData(nome_thread,
                               f'XML - {name_company}',
                               f'Empresa não possui acesso a tela "HWWNotaFiscalEletronica1" para download do XML de serviços prestados...',
                               f'{cnpj_cpf}',
                               'PRESTADOS',
                               'info-gradient',
                               'ERRO',
                               'danger-gradient')

        except Exception as e:
            includeLogData(nome_thread,
                           f'XML - {name_company}',
                           f'Erro ao baixar XML de serviços prestados.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'ATENÇÃO',
                           'warning-gradient')


def exec_GUIAISSQN(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    try:
        home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwencerramento'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()
        print('GUIAISSQN - Executando')
        erro = False
        try:
            campoCompMes = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.NAME, '_INENCMES')))
            selectCompMes = Select(campoCompMes)
            selectCompMes.select_by_value(str(int(execMes)))
            sleep(0.2)
            campoCompAno = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.NAME, '_INENCANO')))
            campoCompAno.send_keys(f"{execAno}")
            sleep(0.2)
            campoTipo = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.NAME, '_INENCTIPO')))
            selectTipo = Select(campoTipo)
            selectTipo.select_by_value(str("P"))  # SERVIÇO PRESTADO GUIA ISSQN
            sleep(0.2)
            campoSubmit = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.NAME, 'SEARCHBUTTON')))
            campoSubmit.click()
            erro = False

        except Exception as e:
            print('Erro DAM(GUIA ISSQN)')
            erro = True

        if erro:
            raise Exception('Erro ao gerar GUIA ISSQN!')

        try:
            WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Não Existe Encerramento com os Dados Informados.']")))
            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/Sem GUIA ISSQN.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")
            alterou_data = False
        except Exception:
            alterou_data = True

        if not alterou_data:
            includeLogData(nome_thread,
                           f'GUIA - {name_company}',
                           f'Emissão de Guia Não Necessária/Empresa sem Movimento Prestado.',
                           f'{cnpj_cpf}',
                           'ISSQN',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')

        if alterou_data:
            linkDAM = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, '//*[@id="TBDAM_0001"]/tbody/tr/td/a')))
            url_gerar = linkDAM.get_attribute("href")
            primeira_aspas = url_gerar.find("'")
            segunda_aspas = url_gerar.find("'", primeira_aspas + 1)
            url_entre_aspas = url_gerar[primeira_aspas + 1:segunda_aspas]
            url_sem_percentil27 = url_entre_aspas.split("%27")[0]
            url_final = url_sem_percentil27
            if url_final:
                try:
                    driver.get(
                        f'http://s32.asp.srv.br:8080/issonline/servlet/{url_final}')
                except TimeoutException:
                    driver.refresh()
                print("ISSQN - Guia pronta para download!")
                try:
                    WebDriverWait(driver, 5).until(
                        EC.frame_to_be_available_and_switch_to_it((By.NAME, 'Embpage'))
                    )
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.XPATH,
                             '//*[@id="open-button"]'))).click()
                except Exception as e:
                    print('Clicou para baixar guia, com except.')

                padrao_nome = 'DOCUMENTO_ARRECADACAO_MUNICIPAL'
                novo_padrao = 'Guia-ISSQN'

                downloaded = False
                while not downloaded:
                    guiasTributo = glob.glob(os.path.join(pastaArquivos, '*' + padrao_nome + '*.pdf'))
                    if len(guiasTributo) >= 1:
                        sleep(2)
                        downloaded = True
                    else:
                        downloaded = False

                guiasTributo = glob.glob(os.path.join(pastaArquivos, '*' + padrao_nome + '*.pdf'))
                for guia in guiasTributo:
                    os.rename(guia, os.path.join(pastaArquivos, novo_padrao + '.pdf'))

                home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hhome'
                try:
                    driver.get(f'{home_page}')
                except TimeoutException:
                    driver.refresh()
                includeLogData(nome_thread,
                               f'GUIA - {name_company}',
                               f'Guia ISSQN baixada com sucesso.',
                               f'{cnpj_cpf}',
                               'ISSQN',
                               'info-gradient',
                               'SUCESSO',
                               'success-gradient')

    except Exception as error:
        includeLogData(nome_thread,
                       f'GUIA - {name_company}',
                       f'Erro ao baixar GUIA ISSQN.',
                       f'{cnpj_cpf}',
                       'ISSQN',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
        print(error)


def exec_GUIAISSQN_old01_01_2024(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    try:
        home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hhome'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()
        print('GUIAISSQN - Executando')
        CampoGuia = driver.find_element(By.XPATH, "//*[text()='Guia de Recolhimento']")
        CampoGuia.click()
        CampoConsulta = driver.find_element(By.XPATH,
                                            "//*[text()='Consulta de Débitos e Emissão de 2ª Via']")
        CampoConsulta.click()
        mes = int(execMes)
        ano = int(execAno)

        CampoCompetencia = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 f"//*[@name='W0010_PARCELAMES']")))
        CampoCompetencia.click()
        # CampoCompetencia_Select = Select(CampoCompetencia)
        # CampoCompetencia_Select.select_by_value = execMes

        for i in range(mes):
            actions.send_keys(Keys.DOWN).perform()
            sleep(0.1)

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "//*[@id='W0010_PARCELAANO']"))).send_keys(execAno)

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 f"//*[@name='W0010SEARCHBUTTON']"))).click()

        # aqui pega o proximo mês (fim dele) para vencimento da guia.
        if mes == 12:
            fim_proximo_mes = datetime(ano + 1, 2, 1) + timedelta(days=-1)
        elif mes == 11:
            fim_proximo_mes = datetime(ano + 1, 1, 1) + timedelta(days=-1)
        else:
            fim_proximo_mes = datetime(ano, mes + 2, 1) + timedelta(days=-1)

        fim_proximo_mes = fim_proximo_mes.strftime("%d/%m/%Y")

        WebDriverWait(driver, 5).until(EC.presence_of_element_located(
            (By.XPATH, '//*[@id="W0010_DATAVENCIMENTO"]'))).send_keys(fim_proximo_mes)

        sleep(100)
        driver.find_element(By.XPATH, '//*[@id="W0010IMGATUALIZARVENCIMENTO"]').click()

        alterou_data = True

        try:
            campoerro = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="W0010TBL4"]/tbody/tr/td/span/menu/li')))
            texto_erro = campoerro.get_attribute("textContent")
            if 'O Máximo de dias permitidos para acréscimo a data de vencimento é de 30 dias.' in texto_erro:
                hoje = datetime.now() + timedelta(days=30)
                limite_vencimento = hoje.strftime("%d/%m/%Y")
                driver.find_element(By.XPATH,
                                    '//*[@id="W0010_DATAVENCIMENTO"]').send_keys(
                    limite_vencimento)
                driver.find_element(By.XPATH,
                                    '//*[@id="W0010IMGATUALIZARVENCIMENTO"]').click()
                includeLogData(nome_thread,
                               f'GUIA - {name_company}',
                               f'Data de vencimento da guia setado para: {limite_vencimento} devido ao limit de 30 dias atingido.',
                               f'{cnpj_cpf}',
                               'ISSQN',
                               'info-gradient',
                               'SUCESSO',
                               'success-gradient')
        except Exception as error:
            print('GUIAISSQN - Alteração da data de vencimento realizada!')

        if not alterou_data:
            includeLogData(nome_thread,
                           f'GUIA - {name_company}',
                           f'Emissão de Guia Não Necessária/Empresa sem Movimento Prestado.',
                           f'{cnpj_cpf}',
                           'ISSQN',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
            raise Exception('Data não alterada!')

        if alterou_data:
            elemento_interar_data = driver.find_elements(By.XPATH,
                                                         '//*[@id="span_W0010TCDPARCELAVENCIMENTO_0001"]')
            for index, elemento in enumerate(elemento_interar_data, start=1):
                texto_do_elemento = elemento.get_attribute("textContent")
                if fim_proximo_mes in texto_do_elemento:
                    index_corresp = index
                    elemento_interar_tributo = driver.find_elements(By.XPATH,
                                                                    '//*[@id="span_W0010IMPABREVIACAO_0001"]')
                    for index2, elemento2 in enumerate(elemento_interar_tributo,
                                                       start=index_corresp):
                        texto_do_elemento = elemento2.get_attribute("textContent")
                        tipo_tributo = 'ISSQN MENS'
                        if tipo_tributo in texto_do_elemento and index == index2:
                            driver.find_element(By.XPATH,
                                                f'//*[@id="W0010GRID1"]/tbody/tr[{index2 + 1}]/td[1]/span/input').click()
                            driver.find_element(By.XPATH,
                                                '//*[@id="W0010BTNAVANCAR"]').click()
                            botaoGerarDAM = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH,
                                                                '//*[@id="W0010TBATUALIZAVENCIMENTO1"]/tbody/tr/td[2]/p/a')))
                            url_gerar = botaoGerarDAM.get_attribute("href")
                            primeira_aspas = url_gerar.find("'")
                            segunda_aspas = url_gerar.find("'", primeira_aspas + 1)
                            url_entre_aspas = url_gerar[primeira_aspas + 1:segunda_aspas]
                            url_sem_percentil27 = url_entre_aspas.split("%27")[0]
                            url_final = url_sem_percentil27
                            if url_final:
                                try:
                                    driver.get(
                                        f'http://s32.asp.srv.br:8080/issonline/servlet/{url_final}')
                                except TimeoutException:
                                    driver.refresh()
                                print("ISSQN - Guia pronta para download!")
                                try:
                                    WebDriverWait(driver, 5).until(
                                        EC.frame_to_be_available_and_switch_to_it((By.NAME, 'Embpage'))
                                    )
                                    WebDriverWait(driver, 5).until(
                                        EC.presence_of_element_located(
                                            (By.XPATH,
                                             '//*[@id="open-button"]'))).click()
                                except Exception as e:
                                    print('Clicou para baixar guia, com except.')

                                padrao_nome = 'DOCUMENTO_ARRECADACAO_MUNICIPAL'
                                novo_padrao = 'Guia-ISSQN'

                                downloaded = False
                                while not downloaded:
                                    guiasTributo = glob.glob(os.path.join(pastaArquivos, '*' + padrao_nome + '*.pdf'))
                                    if len(guiasTributo) >= 1:
                                        sleep(2)
                                        downloaded = True
                                    else:
                                        downloaded = False

                                guiasTributo = glob.glob(os.path.join(pastaArquivos, '*' + padrao_nome + '*.pdf'))
                                for guia in guiasTributo:
                                    os.rename(guia, os.path.join(pastaArquivos, novo_padrao + '.pdf'))

                                home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hhome'
                                try:
                                    driver.get(f'{home_page}')
                                except TimeoutException:
                                    driver.refresh()
                                includeLogData(nome_thread,
                                               f'GUIA - {name_company}',
                                               f'Guia ISSQN baixada com sucesso.',
                                               f'{cnpj_cpf}',
                                               'ISSQN',
                                               'info-gradient',
                                               'SUCESSO',
                                               'success-gradient')
                            else:
                                print("Nenhuma URL encontrada na string.")
                            break
    except Exception as error:
        includeLogData(nome_thread,
                       f'GUIA - {name_company}',
                       f'Erro ao baixar GUIA ISSQN.',
                       f'{cnpj_cpf}',
                       'ISSQN',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
        print(error)


def exec_ENC_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno):
    link_ausencia_tomado = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwminhanotafiscaleletronica'
    mes = int(execMes)
    ano = int(execAno)
    try:
        driver.get(f'{link_ausencia_tomado}')
    except TimeoutException:
        driver.refresh()

    ausencia_tomado = False
    try:
        driver.find_element(By.XPATH,
                            '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select').click()
        driver.find_element(By.XPATH,
                            f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]').click()
        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        qtd_validos_tomado = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="Table3"]/tbody/tr[3]/td[1]/p'))).get_attribute(
            "textContent")
        includeLogData(nome_thread,
                       f'ENCERRAMENTO - {name_company}',
                       f'Qtd. de TOMADOS válidos {qtd_validos_tomado}.',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
        qtd_validos_tomado = int(''.join(filter(str.isdigit, qtd_validos_tomado)))
        if qtd_validos_tomado >= 1:
            ausencia_tomado = False
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Nenhuma ausência a realizar.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
        else:
            ausencia_tomado = True
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Necessário emissão de ausência.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
    except Exception as error:
        includeLogData(nome_thread,
                       f'ENCERRAMENTO - {name_company}',
                       f'Sem acesso a página de ausência de tomados.',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')

    if ausencia_tomado:
        print('AUSENCIA DE TOMADO')
        do_ausencia_tomado = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwausenciaretencao'
        try:
            driver.get(f'{do_ausencia_tomado}')
        except TimeoutException:
            driver.refresh()
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="NEWCONTROL"]'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     '//*[@id="TABLE2"]/tbody/tr/td[2]/select'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     f'//*[@id="TABLE2"]/tbody/tr/td[2]/select/option[{mes}]'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="RETTIPO"]'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="RETTIPO"]/option[3]'))).click()  # TOMADO
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="TABLE6"]/tbody/tr/td[1]/input[1]'))).click()
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Ausência de serviços Tomados realizada com sucesso.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
        except Exception as error:
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Ausência não necessária / não realizada.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'ATENÇÃO',
                           'warning-gradient')
    else:
        try:
            print('RESOLVENDO PENDENCIAS')
            link_encerramento = 'http://s32.asp.srv.br:8080/issonline/servlet/hencerramentomensal'
            try:
                driver.get(f'{link_encerramento}')
            except TimeoutException:
                driver.refresh()
            driver.find_element(By.XPATH, '//*[@id="W0015TAB_0002"]').click()
            tomados_encerrar_pendencias = driver.find_element(By.XPATH,
                                                              '//*[@id="W0017IMGPENDENCIAS"]')
            tomados_encerrar_pendencias.click()
            driver.find_element(By.XPATH, '//*[@id="IMGPENDENCIAS"]').click()
            try:
                link_pendencias = 'http://s32.asp.srv.br:8080/issonline/servlet/hservicotomadopendencias'
                try:
                    driver.get(f'{link_pendencias}')
                except TimeoutException:
                    driver.refresh()
                driver.find_element(By.XPATH, '//*[@id="IMGTODOS"]').click()
                driver.find_element(By.XPATH, '//*[@id="IMGACEITAR"]').click()
                driver.find_element(By.XPATH, '//*[@id="BTNENCERRAR"]').click()
                includeLogData(nome_thread,
                               f'ENCERRAMENTO - {name_company}',
                               f'Encerramento de pendências realizado.',
                               f'{cnpj_cpf}',
                               'TOMADOS',
                               'info-gradient',
                               'SUCESSO',
                               'success-gradient')
            except Exception as error:
                try:
                    driver.get(f'{link_encerramento}')
                except TimeoutException:
                    driver.refresh()

        except (NoSuchElementException, ElementNotInteractableException):
            driver.find_element(By.XPATH, '//*[@id="W0015TAB_0002"]').click()
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Encerramento de pendências realizado.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')

        try:
            print('ENCERRANDO TOMADO')
            link_encerramento = 'http://s32.asp.srv.br:8080/issonline/servlet/hencerramentomensal'
            try:
                driver.get(f'{link_encerramento}')
            except TimeoutException:
                driver.refresh()
            driver.find_element(By.XPATH, '//*[@id="W0015TAB_0002"]').click()
            tomados_encerrar = driver.find_element(By.XPATH,
                                                   '//*[@id="W0017IMGCONSOLIDADO"]')
            tomados_encerrar.click()
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Encerramento de serviços Tomados realizado.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
            try:
                alert = Alert(driver)
                alert.accept()
            except Exception as e:
                print("Não tem botão Alert")
                home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hhome'
                try:
                    driver.get(f'{home_page}')
                except TimeoutException:
                    driver.refresh()

        except (NoSuchElementException, ElementNotInteractableException):
            home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hhome'
            try:
                driver.get(f'{home_page}')
            except TimeoutException:
                driver.refresh()
        home_page = 'http://s32.asp.srv.br:8080/issonline/servlet/hhome'
        try:
            driver.get(f'{home_page}')
        except TimeoutException:
            driver.refresh()


def exec_ENC_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno):
    link_ausencia_prestado = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwnotafiscaleletronica1'
    mes = int(execMes)
    ano = int(execAno)
    try:
        driver.get(f'{link_ausencia_prestado}')
    except TimeoutException:
        driver.refresh()

    ausencia_prestado = False
    try:
        driver.find_element(By.XPATH,
                            '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select').click()
        driver.find_element(By.XPATH,
                            f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]').click()
        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        qtd_validos_prestado = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="Table3"]/tbody/tr[3]/td[1]/p'))).get_attribute(
            "textContent")
        includeLogData(nome_thread,
                       f'ENCERRAMENTO - {name_company}',
                       f'Qtd. de PRESTADOS válidos {qtd_validos_prestado}.',
                       f'{cnpj_cpf}',
                       'PRESTADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
        qtd_validos_prestado = int(''.join(filter(str.isdigit, qtd_validos_prestado)))
        if qtd_validos_prestado >= 1:
            ausencia_prestado = False
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Nenhuma ausência a realizar.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
        else:
            ausencia_prestado = True
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Necessário emissão de ausência.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
    except Exception as error:
        includeLogData(nome_thread,
                       f'ENCERRAMENTO - {name_company}',
                       f'Sem acesso a página de ausência de prestados.',
                       f'{cnpj_cpf}',
                       'PRESTADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')

    if ausencia_prestado:
        print('AUSENCIA DE PRESTADO')
        do_ausencia_prestado = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwausenciaretencao'
        try:
            driver.get(f'{do_ausencia_prestado}')
        except TimeoutException:
            driver.refresh()
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="NEWCONTROL"]'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     '//*[@id="TABLE2"]/tbody/tr/td[2]/select'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     f'//*[@id="TABLE2"]/tbody/tr/td[2]/select/option[{mes}]'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="RETTIPO"]'))).click()
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     '//*[@id="RETTIPO"]/option[2]'))).click()  # PRESTADO
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="TABLE6"]/tbody/tr/td[1]/input[1]'))).click()
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Ausência de serviços Prestados realizada com sucesso.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
        except Exception as error:
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Ausência não necessária / não realizada.',
                           f'{cnpj_cpf}',
                           'PRESTADOS',
                           'info-gradient',
                           'ATENÇÃO',
                           'warning-gradient')
    else:
        print('ENCERRANDO PRESTADO')
        link_encerramento = 'http://s32.asp.srv.br:8080/issonline/servlet/hencerramentomensal'
        try:
            driver.get(f'{link_encerramento}')
        except TimeoutException:
            driver.refresh()

        try:
            driver.find_element(By.XPATH,
                                '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select').click()
            driver.find_element(By.XPATH,
                                f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]').click()
            selectYear = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
            filtroYear = Select(selectYear)
            filtroYear.select_by_visible_text(f"{ano}")
            sleep(0.5)

            prestados_encerrar = driver.find_element(By.XPATH,
                                                     '//*[@id="W0017IMGCONSOLIDADO"]')
            prestados_encerrar.click()
            alert = Alert(driver)
            alert.accept()
            includeLogData(nome_thread,
                           f'ENCERRAMENTO - {name_company}',
                           f'Encerramento de serviços Prestados realizado.',
                           f'{cnpj_cpf}',
                           'TOMADOS',
                           'info-gradient',
                           'SUCESSO',
                           'success-gradient')
        except Exception as e:
            driver.find_element(By.XPATH, '//*[@id="W0015TAB_0002"]').click()


def exec_NFSE_TOMADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
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
    try:
        xml_prestadas = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwminhanotafiscaleletronica'
        driver.get(f'{xml_prestadas}')
        driver.find_element(By.XPATH,
                            '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select').click()
        driver.find_element(By.XPATH,
                            f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]').click()
        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")
        sleep(0.5)

        original_window = driver.current_window_handle
        driver.find_element(By.XPATH, '//*[@id="IMGIMPRIMIR"]').click()

        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        for window_handle in driver.window_handles:
            if window_handle != original_window:
                driver.switch_to.window(window_handle)
                break

        current_url = driver.current_url
        driver.close()
        driver.switch_to.window(original_window)
        try:
            driver.get(current_url)
        except TimeoutException:
            driver.refresh()

        CampoInicio = driver.find_element(By.XPATH, '//*[@id="_NUMINICIAL"]')
        CampoInicio.clear()
        CampoInicio.send_keys('1')
        CampoFinal = driver.find_element(By.XPATH, '//*[@id="_NUMFINAL"]')
        CampoFinal.clear()
        CampoFinal.send_keys('1000000000')
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="TABLE1"]/tbody/tr[3]/td/p/input'))).click()
        driver.switch_to.frame('Embpage')

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="open-button"]'))).click()

        downloaded = False
        while not downloaded:
            arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.pdf'))
            for arquivo in arquivos_zip:
                if 'Nota_Fiscal_Eletronica_' in arquivo:
                    if verify_downloaded(arquivo) is True:
                        downloaded = True
                    else:
                        downloaded = False
        sleep(1)
        arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.pdf'))
        for arquivo in arquivos_zip:
            if 'Nota_Fiscal_Eletronica_' in arquivo:
                novo_nome_xml = f"{pastaArquivos}/NOTAS - Tomado.pdf"
                if os.path.exists(novo_nome_xml):
                    os.remove(novo_nome_xml)
                os.rename(arquivo, novo_nome_xml)

        includeLogData(nome_thread,
                       f'NFSE - {name_company}',
                       f'PDF de notas de serviços Tomados baixado com sucesso.',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'SUCESSO',
                       'success-gradient')

    except Exception as Error:
        includeLogData(nome_thread,
                       f'NFSE - {name_company}',
                       f'Não há PDF de serviços Tomados.',
                       f'{cnpj_cpf}',
                       'TOMADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
        driver.execute_script("document.body.style.zoom = '75%'")
        pasta_destino = f"{pastaArquivos}/ERRO PDF NOTAS TOMADO.png"
        if os.path.exists(pasta_destino):
            os.remove(pasta_destino)
        driver.save_screenshot(pasta_destino)
        driver.execute_script("document.body.style.zoom = '100%'")


def exec_NFSE_PRESTADOS(driver, nome_thread, name_company, cnpj_cpf, execMes, execAno, pastaArquivos):
    mes = int(execMes)
    ano = int(execAno)

    includeLogData(nome_thread,
                   f'NFSE - {name_company}',
                   f'Iniciando processo de download de NFSe de serviços Prestados.',
                   f'{cnpj_cpf}',
                   'PRESTADOS',
                   'info-gradient',
                   'SUCESSO',
                   'success-gradient')

    try:
        xml_prestadas = 'http://s32.asp.srv.br:8080/issonline/servlet/hwwnotafiscaleletronica1'
        driver.get(f'{xml_prestadas}')
        driver.find_element(By.XPATH,
                            '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select').click()
        driver.find_element(By.XPATH,
                            f'//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[2]/select/option[{mes}]').click()
        selectYear = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="W0004TBCOMPETENCIA"]/tbody/tr/td[4]/select')))
        filtroYear = Select(selectYear)
        filtroYear.select_by_visible_text(f"{ano}")

        '##### BAIXA O EXCEL PARA PEGAR MAIOR E MENOR NUMERO DE NOTA DO LOTE #####'
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="CTRLEXPORT"]'))).click()

        downloaded = False
        while not downloaded:
            arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.xls'))
            for arquivo in arquivos_zip:
                if 'WWNotaFiscalEletronica' in arquivo:
                    if verify_downloaded(arquivo) is True:
                        downloaded = True
                    else:
                        downloaded = False
        sleep(0.5)

        arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.xls'))
        for arquivo in arquivos_zip:
            if 'WWNotaFiscalEletronica' in arquivo:
                listaNotas = pd.read_excel(arquivo)
                notaMin = listaNotas['Nota'].min()
                notaMax = listaNotas['Nota'].max()
                if os.path.exists(arquivo):
                    os.remove(arquivo)

        try:
            script = "document.querySelector('[id*=\'gxModalWindowDiv\']').style.display = 'none';"
            driver.execute_script(script)
        except Exception:
            sleep(2)

        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 '//*[@id="IMGIMPRIMIR"]'))).click()
        original_window = driver.current_window_handle

        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        for window_handle in driver.window_handles:
            if window_handle != original_window:
                driver.switch_to.window(window_handle)
                break

        current_url = driver.current_url
        driver.close()
        driver.switch_to.window(original_window)
        try:
            driver.get(current_url)
        except TimeoutException:
            driver.refresh()

        maxNotasPorDownload = 50
        arquivosPDFCriados = []
        for notaInicio in range(notaMin, notaMax, maxNotasPorDownload):
            notaFinal = min(notaInicio + maxNotasPorDownload - 1, notaMax)

            driver.find_element(By.XPATH, '//*[@id="_NUMINICIAL"]').send_keys(f'{notaInicio}')
            CampoFinal = driver.find_element(By.XPATH, '//*[@id="_NUMFINAL"]')
            CampoFinal.clear()
            CampoFinal.send_keys(f'{notaFinal}')
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="TBL20"]/tbody/tr[3]/td/p/input'))).click()
            driver.switch_to.frame('Embpage')

            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="open-button"]'))).click()

            downloaded = False
            while not downloaded:
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.pdf'))
                for arquivo in arquivos_zip:
                    if 'Nota_Fiscal_Eletronica_' in arquivo:
                        if verify_downloaded(arquivo) is True:
                            downloaded = True
                        else:
                            downloaded = False
            sleep(0.5)
            arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.pdf'))
            for arquivo in arquivos_zip:
                if 'Nota_Fiscal_Eletronica_' in arquivo:
                    novo_nome_xml = f"{pastaArquivos}/NOTAS - Prestados {notaInicio}-{notaFinal}.pdf"
                    if os.path.exists(novo_nome_xml):
                        os.remove(novo_nome_xml)
                    os.rename(arquivo, novo_nome_xml)

                    '#CRIA LISTA DE PDFS#'
                    arquivosPDFCriados.append(novo_nome_xml)

            '#### ENTRA NOVAMENTE NA PAGINA PARA INSERIR NOTAS ####'
            try:
                driver.get(current_url)
            except TimeoutException:
                driver.refresh()

        if notaMax % maxNotasPorDownload != 0:
            '#### BAIXA O ULTIMO ARQUIVO PARA GARANTIR O RESTANTE DOS ARQUIVOS ####'
            ultimoNotaMin = (notaMax // maxNotasPorDownload) * maxNotasPorDownload + 1

            driver.find_element(By.XPATH, '//*[@id="_NUMINICIAL"]').send_keys(f'{ultimoNotaMin}')
            CampoFinal = driver.find_element(By.XPATH, '//*[@id="_NUMFINAL"]')
            CampoFinal.clear()
            CampoFinal.send_keys(f'{notaMax}')
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="TBL20"]/tbody/tr[3]/td/p/input'))).click()
            driver.switch_to.frame('Embpage')

            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="open-button"]'))).click()

            downloaded = False
            while not downloaded:
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.pdf'))
                for arquivo in arquivos_zip:
                    if 'Nota_Fiscal_Eletronica_' in arquivo:
                        if verify_downloaded(arquivo) is True:
                            downloaded = True
                        else:
                            downloaded = False
            sleep(0.5)
            arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.pdf'))
            for arquivo in arquivos_zip:
                if 'Nota_Fiscal_Eletronica_' in arquivo:
                    os.remove(arquivo)
            sleep(1)

        pdf_writer = PyPDF2.PdfWriter()
        for arquivo in arquivosPDFCriados:
            with open(arquivo, 'rb') as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                for pagina in range(len(pdf_reader.pages)):
                    pagina_atual = pdf_reader.pages[pagina]
                    pdf_writer.add_page(pagina_atual)

            os.remove(arquivo)

        ArquivoFinal = f"{pastaArquivos}/NOTAS - Prestados.pdf"
        with open(ArquivoFinal, 'wb') as pdf_output:
            pdf_writer.write(pdf_output)

        includeLogData(nome_thread,
                       f'NFSE - {name_company}',
                       f'PDF de notas de serviços Prestados baixado com sucesso.',
                       f'{cnpj_cpf}',
                       'PRESTADOS',
                       'info-gradient',
                       'SUCESSO',
                       'success-gradient')

    except Exception as Error:
        sleep(2)
        includeLogData(nome_thread,
                       f'NFSE - {name_company}',
                       f'Não há PDF de serviços Prestados.',
                       f'{cnpj_cpf}',
                       'PRESTADOS',
                       'info-gradient',
                       'ATENÇÃO',
                       'warning-gradient')
