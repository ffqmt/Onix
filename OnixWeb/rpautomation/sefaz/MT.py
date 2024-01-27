import shutil
import threading

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

# from apps.authentication.models import Companies, ReportsRefreshControl, FilesParameters
# from apps.configs.globals import Globals
from OnixWeb.addons.appscontext import *

from webdriver_auto_update.webdriver_auto_update import WebdriverAutoUpdate

from OnixWeb.addons.models import PessoaJuridica, logData, ThreadingCounter, PessoaFisica, Empresas, AgendamentosRPA
from OnixWeb.addons.util import log_message, verify_downloaded

import base64
from PIL import Image
import cv2
from io import BytesIO
import easyocr
import re

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
        'nfe_saida': bool(Pessoa.sefaz_nfe_saida),
        'nfe_entrada': bool(Pessoa.sefaz_nfe_entrada),
        'cte_emissor': bool(Pessoa.sefaz_cte_emitido),
        'cte_tomador': bool(Pessoa.sefaz_cte_tomado),
        'nfce_emitida': bool(Pessoa.sefaz_nfce),
    }


def dadosLoginSefaz(EmpresaExec):
    with app.app_context():
        Empresa = Empresas.query.filter_by(id=EmpresaExec).first()

    return {'login': Empresa.login_contabilista, 'senha': Empresa.senha_contabilista}


def MainExecution_Juridica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    AtualizarChromeDriver()
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
            tipo_exec = 'PJ'
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
            nome_empresa = f"{name_company} - {username}"
            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['nfe_saida'] or listaParametros['nfe_entrada']:
                RegistrosNFe = verify_NFE_SAIDAENTRADA(driver=driver,
                                                       nome_thread=nome_thread,
                                                       tipo_exec=tipo_exec,
                                                       name_company=name_company,
                                                       cnpj_cpf=username,
                                                       idDoc=username,
                                                       execMes=mesExec,
                                                       execAno=anoExec,
                                                       pastaArquivos=pastaArquivos)
                if RegistrosNFe:
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
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger')

    '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
    sleep(3)
    driver.close()


def MainExecution_Juridica_Padrao(listaPessoas, EmpresaExec, Ano, Mes):
    AtualizarChromeDriver()
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
            nome_empresa = f"{name_company} - {username}"
            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['nfe_saida'] or listaParametros['nfe_entrada']:
                RegistrosNFe = verify_NFE_SAIDAENTRADA(driver=driver,
                                                       nome_thread=nome_thread,
                                                       tipo_exec=tipo_exec,
                                                       name_company=name_company,
                                                       cnpj_cpf=username,
                                                       idDoc=username,
                                                       execMes=mesExec,
                                                       execAno=anoExec,
                                                       pastaArquivos=pastaArquivos)
                if RegistrosNFe:
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
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger')

    '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
    sleep(3)
    driver.close()


def MainExecution_Fisica_Expecifico(listaPessoas, listaParametros, EmpresaExec, Ano, Mes):
    AtualizarChromeDriver()
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPF(listaPessoas, EmpresaExec)
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
            nome_empresa = f"{name_company} - {ie}"
            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['nfe_saida'] or listaParametros['nfe_entrada']:
                RegistrosNFe = verify_NFE_SAIDAENTRADA(driver=driver,
                                                       nome_thread=nome_thread,
                                                       tipo_exec=tipo_exec,
                                                       name_company=name_company,
                                                       cnpj_cpf=username,
                                                       idDoc=ie,
                                                       execMes=mesExec,
                                                       execAno=anoExec,
                                                       pastaArquivos=pastaArquivos)
                if RegistrosNFe:
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
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger')

    '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
    sleep(3)
    driver.close()


def MainExecution_Fisica_Padrao(listaPessoas, EmpresaExec, Ano, Mes):
    AtualizarChromeDriver()
    thread_atual = threading.current_thread()
    nome_thread = thread_atual.name
    caminho_pasta = os.path.join(root_path, fr'OnixWeb\rpautomation\transactionFiles\{nome_thread}')
    dados = dadosPessoasPF(listaPessoas, EmpresaExec)
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
            nome_empresa = f"{name_company} - {ie}"
            pastaArquivos = os.path.join(caminho_pasta, nome_empresa, anoExec, mesExec)
            if not os.path.exists(pastaArquivos):
                os.makedirs(pastaArquivos)

            driver.execute_cdp_cmd('Page.setDownloadBehavior',
                                   {'behavior': 'allow', 'downloadPath': rf'{pastaArquivos}'})

            '######### EXECUTA ESCOLHAS APOS LOGADO ########'
            if listaParametros['nfe_saida'] or listaParametros['nfe_entrada']:
                RegistrosNFe = verify_NFE_SAIDAENTRADA(driver=driver,
                                                       nome_thread=nome_thread,
                                                       tipo_exec=tipo_exec,
                                                       name_company=name_company,
                                                       cnpj_cpf=username,
                                                       idDoc=ie,
                                                       execMes=mesExec,
                                                       execAno=anoExec,
                                                       pastaArquivos=pastaArquivos)
                if RegistrosNFe:
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
        includeLogData(nome_thread,
                       f'ARQUIVO FINAL',
                       'Erro ao gerar arquivo!',
                       'BOT',
                       'RPA',
                       'primary-gradient',
                       'ERRO',
                       'danger')

    '########## FINALIZA O DRIVER APOS REALIZAR O PROCESSO DE TODAS AS EMPRESAS, EM UM UNICO DRIVER #########'
    sleep(3)
    driver.close()


def MainExecution_Agendamentos(idAgendamento, idEstado):
    with app.app_context():
        dadosAgendamento = AgendamentosRPA.query.filter_by(id=idAgendamento).first()
        dadosAgendamento.status = 'Em Execução'
        db.session.commit()
    sleep(300)
    print('##########EXECUTOU############')


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


def AtualizarChromeDriver():
    try:
        chromedriverpath = os.path.join(root_path, fr"OnixWeb\rpautomation\dependencias\chromedriver")
        WebdriverAutoUpdate(chromedriverpath).check_driver()
    except Exception as e:
        print(e, 'Erro ao atualizar Chromedriver!')


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


def exec_LOGIN(driver, nome_thread, login_sefaz_contabilista, senha_sefaz_contabilista):
    includeLogData(nome_thread,
                   f'LOGIN - CONTABILISTA',
                   f'Realizando login...',
                   f'BOT',
                   'SEFAZ',
                   'warning-gradient',
                   'ATENÇÃO',
                   'warning-gradient')
    actions = ActionChains(driver)
    sefaz = 'https://www.sefaz.mt.gov.br/acesso/pages/login/login.xhtml'
    try:
        driver.get(sefaz)
    except TimeoutException:
        driver.refresh()

    recaptcha = ''
    recaptchalen = 0
    logado = False

    while not recaptchalen == 4:
        campoAtualizaCaptcha = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[text()='Clique aqui se não visualizar a imagem.']")))
        campoAtualizaCaptcha.click()
        sleep(0.2)
        base64_link = driver.find_element(By.XPATH,
                                          '//*[@id="formLogin:superPanel"]/div[3]/div/img').get_attribute(
            "src")
        if base64_link.startswith('data:image/png;base64,'):
            base64_link = base64_link.replace('data:image/png;base64,', '')
        missing_padding = len(base64_link) % 4
        if missing_padding:
            base64_link += '=' * (4 - missing_padding)
        image_name = f'{root_path}/OnixWeb/rpautomation/sefaz/CaptchaSolver/recaptcha.png'
        image_data = base64.b64decode(base64_link)
        image = Image.open(BytesIO(image_data))
        image.save(image_name, 'PNG')
        img = cv2.imread(image_name, cv2.IMREAD_GRAYSCALE)
        img = cv2.medianBlur(img, 3)
        # ret, th1 = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        # th2 = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, 2)
        # th3 = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        cv2.imwrite(f'{root_path}/OnixWeb/rpautomation/sefaz/CaptchaSolver/recaptcha_tratado.png', img)
        reader = easyocr.Reader(['pt'], gpu=True)
        resultado = reader.readtext(
            f'{root_path}/OnixWeb/rpautomation/sefaz/CaptchaSolver/recaptcha_tratado.png')
        try:
            recaptcha = re.sub(r'[^a-zA-Z0-9]', '', ''.join(resultado[0][1].split()).lower())
            recaptchalen = len(str(recaptcha))
            if recaptchalen == 4:
                'print(recaptcha)'
        except Exception as e:
            recaptchalen = 0

        if recaptchalen == 4:
            try:
                driver.find_element(By.XPATH, '//*[@id="formLogin:selectTipoUsuario_label"]').click()
                sleep(0.2)
                driver.find_element(By.XPATH, '//*[@id="formLogin:selectTipoUsuario_1"]').click()
                sleep(1)
                driver.find_element(By.XPATH, '//*[@id="formLogin:inputLogin"]').send_keys(login_sefaz_contabilista)
                sleep(1)
                driver.find_element(By.XPATH, '//*[@id="formLogin:inputSenha"]').send_keys(senha_sefaz_contabilista)
                sleep(1)
                driver.find_element(By.XPATH, '//*[@id="formLogin:inputCaptcha"]').send_keys(recaptcha)
                sleep(1)
                actions.send_keys(Keys.ENTER).perform()
                logado = False
                try:
                    pagina_inicial_logado = 'https://www.sefaz.mt.gov.br/acesso/pages/paginainicial.xhtml'
                    WebDriverWait(driver, 10).until(EC.url_to_be(pagina_inicial_logado))
                    logado = True
                except Exception as e:
                    logado = False
                    recaptchalen = 0

                if not logado:
                    try:
                        driver.get(sefaz)
                    except TimeoutException:
                        driver.refresh()
                    raise Exception('Não Logado')

            except Exception as e:
                print('Ainda não logou.')

    includeLogData(nome_thread,
                   'LOGIN - CONTABILISTA',
                   'Acesso realizado com sucesso.',
                   'BOT',
                   'SEFAZ',
                   'warning-gradient',
                   'SUCESSO',
                   'success-gradient')

    return logado


def verify_NFE_SAIDAENTRADA(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno,
                            pastaArquivos):
    actions = ActionChains(driver)
    temregistrosNFE = False
    if not temregistrosNFE:
        try:
            consultas = 'https://www.sefaz.mt.gov.br/nfe/pages/consultaemitidasrecebidas/consultaemitidasrecebidas.xhtml'
            try:
                driver.get(consultas)
            except TimeoutException:
                driver.refresh()

            campoTipoDocumento = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "label[id$=':tipoDoct_label']")))
            campoTipoDocumento.click()
            sleep(0.2)

            if tipo_exec == 'PJ':
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'tipoDoct_1')]"))).click()
            elif tipo_exec == 'PF':
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'tipoDoct_0')]"))).click()

            sleep(0.2)

            campoInput = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id$=':numrDoct']")))
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
            inicio_mes = datetime(ano, mes, 1)
            if mes == 12:
                fim_mes = datetime(ano, mes, day=31)
            else:
                fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
            inicio_mes = inicio_mes.strftime("%d/%m/%Y")
            fim_mes = fim_mes.strftime("%d/%m/%Y")

            campoDtInicial = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id$=':dataInicial_input']")))
            for char in f'{inicio_mes}':
                campoDtInicial.send_keys(char)
            sleep(0.2)
            actions.send_keys(Keys.TAB).perform()
            campoDtFinal = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[id$=':dataFinal_input']")))
            for char in f'{fim_mes}':
                campoDtFinal.send_keys(char)
            sleep(0.2)

            campoConsulta = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(@id, 'btnConsEmitReceb')]")))
            campoConsulta.click()
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="primefacesmessagedlg"]')))
                msgerro = driver.find_element(By.XPATH, '//*[@id="primefacesmessagedlg"]')
                if msgerro.get_attribute("aria-live") == 'polite':
                    pasta_destino = f"{pastaArquivos}/NFe-Sem-Saida e Entrada.png"
                    if os.path.exists(pasta_destino):
                        os.remove(pasta_destino)
                    driver.save_screenshot(pasta_destino)
                    driver.find_element(By.XPATH,
                                        '//*[@id="primefacesmessagedlg"]/div[1]/a/span').click()
                    temregistrosNFE = False

                includeLogData(nome_thread,
                               f'NFe - {name_company}',
                               f'Pessoa não possui NFes de Saída/Entrada.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'ATENÇÃO',
                               'warning-gradient')

            except Exception as e:
                temregistrosNFE = True
        except Exception as e:
            print('error#1')
            print(e)
    return temregistrosNFE


def exec_NFE_SAIDA(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    possuiregistrosSaidas = True
    try:
        nenhumRegistroSaidas = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(@id, 'dtResultCons_data')]/tr/td")))
        textoRegistro = nenhumRegistroSaidas.get_attribute("textContent")
        if textoRegistro == 'Nenhuma NF-e foi encontrada':
            blockDadosConsultas = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(@id, 'tabDadosCons')]")))
            driver.execute_script(
                "arguments[0].style.setProperty('display', 'block', 'important');",
                blockDadosConsultas)
            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Saidas.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")
            possuiregistrosSaidas = False
            includeLogData(nome_thread,
                           f'NFe - {name_company}',
                           f'Pessoa não possui NFes de Saída.',
                           f'{cnpj_cpf}',
                           'SEFAZ',
                           'warning-gradient',
                           'ATENÇÃO',
                           'warning-gradient')
    except Exception as e:
        print('error#2')
        # print(e)

    if possuiregistrosSaidas:
        try:
            CampoDownload = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[text()='Exportar para Excel']")))
            CampoDownload.click()
        except Exception as e:
            print('error#3')
            print(e)
        sleep(2)

        consultas = 'https://www.sefaz.mt.gov.br/nfe/pages/consultaemitidasrecebidas/consultaemitidasrecebidas.xhtml'
        try:
            driver.get(consultas)
        except TimeoutException:
            driver.refresh()
        sleep(0.5)
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

        includeLogData(nome_thread,
                       f'NFe - {name_company}',
                       f'Arquivos (Excel) NFes de Saída baixado com sucesso.',
                       f'{cnpj_cpf}',
                       'SEFAZ',
                       'warning-gradient',
                       'SUCESSO',
                       'success-gradient')


def exec_NFE_ENTRADA(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    possuiregistrosEntradas = True
    consultas = 'https://www.sefaz.mt.gov.br/nfe/pages/consultaemitidasrecebidas/consultaemitidasrecebidas.xhtml'
    try:
        driver.get(consultas)
    except TimeoutException:
        driver.refresh()
    try:
        FlagDestinatario = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH,
                 "//*[contains(@id, 'sorEmissorDest')]/tbody/tr/td[2]/div/div[2]/span")))
        FlagDestinatario.click()
    except Exception as e:
        print('error#4')
        print(e)
    sleep(0.2)
    campoTipoDocumento = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "label[id$=':tipoDoct_label']")))
    campoTipoDocumento.click()
    sleep(0.2)
    if tipo_exec == 'PJ':
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'tipoDoct_1')]"))).click()
    elif tipo_exec == 'PF':
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'tipoDoct_0')]"))).click()

    sleep(1)
    campoInput = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[id$=':numrDoct']")))
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
    inicio_mes = datetime(ano, mes, 1)
    if mes == 12:
        fim_mes = datetime(ano, mes, day=31)
    else:
        fim_mes = datetime(ano, mes + 1, 1) + timedelta(days=-1)
    inicio_mes = inicio_mes.strftime("%d/%m/%Y")
    fim_mes = fim_mes.strftime("%d/%m/%Y")

    campoDtInicial = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[id$=':dataInicial_input']")))
    for char in f'{inicio_mes}':
        campoDtInicial.send_keys(char)
    sleep(0.2)
    actions.send_keys(Keys.TAB).perform()
    campoDtFinal = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[id$=':dataFinal_input']")))
    for char in f'{fim_mes}':
        campoDtFinal.send_keys(char)
    sleep(0.2)

    campoConsulta = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "//*[contains(@id, 'btnConsEmitReceb')]")))
    campoConsulta.click()
    sleep(0.5)

    try:
        nenhumRegistroEntradas = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(@id, 'dtResultCons_data')]/tr/td")))
        textoRegistro = nenhumRegistroEntradas.get_attribute("textContent")
        if textoRegistro == 'Nenhuma NF-e foi encontrada':
            blockDadosConsultas = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//*[contains(@id, 'tabDadosCons')]")))
            driver.execute_script(
                "arguments[0].style.setProperty('display', 'block', 'important');",
                blockDadosConsultas)
            driver.execute_script("document.body.style.zoom = '75%'")
            pasta_destino = f"{pastaArquivos}/NFe-Sem-Entradas.png"
            if os.path.exists(pasta_destino):
                os.remove(pasta_destino)
            driver.save_screenshot(pasta_destino)
            driver.execute_script("document.body.style.zoom = '100%'")
            possuiregistrosEntradas = False
            sleep(0.5)
            includeLogData(nome_thread,
                           f'NFe - {name_company}',
                           f'Pessoa não possui NFes de Entrada.',
                           f'{cnpj_cpf}',
                           'SEFAZ',
                           'warning-gradient',
                           'ATENÇÃO',
                           'warning-gradient')
    except Exception as e:
        sleep(0.2)
    if possuiregistrosEntradas:
        try:
            CampoDownload = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//*[text()='Exportar para Excel']")))
            CampoDownload.click()
        except Exception as e:
            ''
        sleep(2)
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

        includeLogData(nome_thread,
                       f'NFe - {name_company}',
                       f'Arquivos (Excel) NFes de Entrada baixado com sucesso.',
                       f'{cnpj_cpf}',
                       'SEFAZ',
                       'warning-gradient',
                       'SUCESSO',
                       'success-gradient')


def exec_CTE_EMISSOR(driver, nome_thread, tipo_exec, name_company, cnpj_cpf, idDoc, execMes, execAno, pastaArquivos):
    actions = ActionChains(driver)
    temregistrosCTE = False
    if not temregistrosCTE:
        try:
            consultascte = 'https://www.sefaz.mt.gov.br/cte/portal/consultaremitidorecebido'
            try:
                driver.get(consultascte)
            except TimeoutException:
                print('### Timeout SEFAZ CTE ###')
                try:
                    driver.get(consultascte)
                except TimeoutException:
                    driver.refresh()
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
                'Entrou na Tela de Consulta'

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
                                consultascte = 'https://www.sefaz.mt.gov.br/cte/portal/consultaremitidorecebido'
                                try:
                                    driver.get(consultascte)
                                except TimeoutException:
                                    driver.refresh()
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
                "'print('Carregou!')'"
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

                try:
                    driver.get(consultascte)
                except TimeoutException:
                    driver.refresh()
            except Exception as e:
                temregistrosCTE = True
        except Exception as e:
            print('error#5')
            print(e)
            # raise Exception(e)

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
            'Possui registros Emissor!'
            sleep(0.2)

        if possuiregistrosEmissor:
            try:
                CampoDownload = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="btnGerarExcelConsulta"]')))
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
            try:
                driver.get(consultascte)
            except TimeoutException:
                print('### Timeout SEFAZ CTE ###')
                try:
                    driver.get(consultascte)
                except TimeoutException:
                    driver.refresh()
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
                'Entrou na Tela de Consulta'

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
                                consultascte = 'https://www.sefaz.mt.gov.br/cte/portal/consultaremitidorecebido'
                                try:
                                    driver.get(consultascte)
                                except TimeoutException:
                                    driver.refresh()
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
                "'print('Carregou!')'"
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

                try:
                    driver.get(consultascte)
                except TimeoutException:
                    driver.refresh()
            except Exception as e:
                temregistrosCTE = True
        except Exception as e:
            print('error#5')
            # raise Exception(e)

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
    actions = ActionChains(driver)
    if ie:
        temregistrosNFC = False
        if not temregistrosNFC:
            try:
                consultasnfce = 'https://www.sefaz.mt.gov.br/nfce/consultarnfceemitidas'
                try:
                    driver.get(consultasnfce)
                except TimeoutException:
                    driver.refresh()
                inscricao_estadual = f'{ie}'
                driver.find_element(By.XPATH, '//*[@id="numrInscEstd"]').send_keys(
                    inscricao_estadual)
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
                    EC.presence_of_element_located((By.NAME, f"bttnConsultar")))
                campoConsulta.click()

                try:
                    inscricao_invalida = Alert(driver)
                    text_erro = inscricao_invalida.text
                    includeLogData(nome_thread,
                                   f'NFCe - {name_company}',
                                   f'{text_erro}',
                                   f'{cnpj_cpf}',
                                   'SEFAZ',
                                   'warning-gradient',
                                   'ERRO',
                                   'danger-gradient')
                    temregistrosNFC = False
                    inscricao_invalida.accept()
                except Exception as e:
                    temregistrosNFC = False
                try:
                    msg_erro = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located(
                            (By.CLASS_NAME, f"SEFAZ-FONT-MensagemErro"))).get_attribute(
                        "textContent")
                    if 'Nenhuma NFC-e Emitida para o Contribuinte' in msg_erro or 'Contabilista não representa o contribuinte' in msg_erro:
                        pasta_destino = f"{pastaArquivos}/NFCe-Sem Emissoes.png"
                        if os.path.exists(pasta_destino):
                            os.remove(pasta_destino)
                        driver.save_screenshot(pasta_destino)
                        temregistrosNFC = False
                    includeLogData(nome_thread,
                                   f'NFCe - {name_company}',
                                   f'{msg_erro}',
                                   f'{cnpj_cpf}',
                                   'SEFAZ',
                                   'warning-gradient',
                                   'ATENÇÃO',
                                   'warning-gradient')
                    try:
                        driver.get(consultasnfce)
                    except TimeoutException:
                        driver.refresh()
                except Exception as e:
                    temregistrosNFC = True
            except Exception as e:
                temregistrosNFC = False

        if temregistrosNFC:
            try:
                NomeParcial = 'ConsultaNFCeEmitidas'
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                for arquivo in arquivos_zip:
                    if NomeParcial in arquivo:
                        os.remove(arquivo)
                CampoDownload = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="bttnExcel"]')))
                CampoDownload.click()
            except Exception as e:
                print('error#9')
                print(e)

            downloaded = False
            while not downloaded:
                NomeParcial = 'ConsultaNFCeEmitidas'
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                for arquivo in arquivos_zip:
                    if NomeParcial in arquivo:
                        if verify_downloaded(arquivo):
                            downloaded = True
                        else:
                            downloaded = False
                        sleep(1)
            else:
                NomeParcialPlanilha = 'Planilha'
                arquivos_planilha_remover = glob.glob(os.path.join(pastaArquivos, '*.xls'))
                for arquivo in arquivos_planilha_remover:
                    if NomeParcialPlanilha in arquivo:
                        if os.path.exists(arquivo):
                            os.remove(arquivo)
                    if 'NFCe Emitidas' in arquivo:
                        if os.path.exists(arquivo):
                            os.remove(arquivo)

                NomeParcial = 'ConsultaNFCeEmitidas'
                arquivos_zip = glob.glob(os.path.join(pastaArquivos, '*.zip'))
                for arquivo in arquivos_zip:
                    if NomeParcial in arquivo:
                        with zipfile.ZipFile(arquivo, 'r') as nome_zip:
                            nome_zip.extractall(path=pastaArquivos, pwd=None)
                arquivos_planilha = glob.glob(os.path.join(pastaArquivos, '*.xls'))
                for arquivo_planilha in arquivos_planilha:
                    if NomeParcialPlanilha in arquivo_planilha:
                        novo_nome_planilha = fr'{pastaArquivos}\NFCe Emitidas.xls'
                        os.rename(arquivo_planilha, novo_nome_planilha)

                includeLogData(nome_thread,
                               f'NFCe - {name_company}',
                               f'Arquivos (Excel) NFCes Emitidas Baixado com sucesso.',
                               f'{cnpj_cpf}',
                               'SEFAZ',
                               'warning-gradient',
                               'SUCESSO',
                               'success-gradient')
    else:
        includeLogData(nome_thread,
                       f'NFCe - {name_company}',
                       f'Pessoa não possui Inscrição Estadual cadastrada para retirar relatório de NFCE.',
                       f'{cnpj_cpf}',
                       'SEFAZ',
                       'warning-gradient',
                       'ERRO',
                       'danger-gradient')
