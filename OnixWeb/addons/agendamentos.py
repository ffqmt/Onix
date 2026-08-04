import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from OnixWeb.addons.appscontext import *
from OnixWeb.addons.models import AgendamentosRPA, Empresas, City, UF, ThreadingCounter, logData
from OnixWeb.addons.util import AtualizarChromeDriver
import hashlib
import os
from OnixWeb.rpautomation.prefeituras import MT_1
from OnixWeb.rpautomation.sefaz import MT
import pytz

# CONFIGURAÇÃO DO SCHEDULE
jobstore = MemoryJobStore()
scheduler = BackgroundScheduler(jobstore=jobstore, timezone="America/Cuiaba")
scheduler.api_enabled = True
fuso_horario = pytz.timezone("America/Cuiaba")

root_path = os.path.abspath('')


# AGENDAMENTO DE ATUALIZAÇÃO DO CHROMEDRIVER
scheduler.add_job(
    id='AtualizadorCD',
    func=AtualizarChromeDriver,
    args=(root_path,),
    trigger='cron',
    day='*',
    hour=12,
    minute=00
)


def chamaExec(agendamentoID):
    with app.app_context():
        agendamento = AgendamentosRPA.query.filter_by(id=agendamentoID).first()
        idCidUF = agendamento.cd_ufcidade_agendamento
        idAgendamento = agendamento.id
        codigo_unico = hashlib.sha256(os.urandom(16)).hexdigest()
        newThreadLogid = ThreadingCounter()
        newThreadLogid.thread_name = f"{codigo_unico}"
        newThreadLogid.orgao_exec = f'{agendamento.tipo_agendamento}'
        newThreadLogid.tipo_exec = 'AGENDAMENTO'
        newThreadLogid.user_exec = 'ONIXSOLUTIONS'
        newThreadLogid.id_empresa = agendamento.id_empresa
        newThreadLogid.data_exec = datetime.now()
        newThreadLogid.nome_arquivo = agendamento.empresa.nome.split()[0].upper()

        threadDataLog = logData()
        threadDataLog.thread_name = f"{codigo_unico}"
        threadDataLog.log_title = 'Iniciando...'
        threadDataLog.log_desc = 'RPA iniciado.'
        threadDataLog.cnpj_cpf = 'BOT'
        threadDataLog.data = datetime.now()
        threadDataLog.tipo = 'BOT'
        threadDataLog.bg_tipo = 'primary-gradient'
        threadDataLog.status = 'SUCESSO'
        threadDataLog.bg_status = 'success-gradient'

        db.session.add(newThreadLogid)
        db.session.add(threadDataLog)
        db.session.commit()

        if agendamento.tipo_agendamento == 'SEFAZ':
            estado = UF.query.filter_by(id=idCidUF).first()
            callExec = getattr(globals()[estado.uf], 'MainExecution_Agendamentos', None)
            if callExec is not None and callable(callExec):
                t = threading.Thread(target=callExec,
                                     name=f"{codigo_unico}",
                                     args=(idAgendamento, estado.id)
                                     )
                t.start()

        elif agendamento.tipo_agendamento == 'PREFEITURA':
            cidade = City.query.filter_by(id=idCidUF).first()
            callExec = getattr(globals()[cidade.uf + '_' + f"{cidade.id}"], 'MainExecution_Agendamentos', None)
            if callExec is not None and callable(callExec):
                processos_str = agendamento.processos_inclusos.strip('[]')
                processos_inclusos = [p.strip().strip('"') for p in processos_str.split(',')]

                # Criando dicionário de parâmetros
                listaParametros = {
                    'enc_taken': 'enc_tomado' in processos_inclusos,
                    'enc_provided': 'enc_prestado' in processos_inclusos,
                    'issqn': 'guia_issqn' in processos_inclusos,
                    'taken': 'rel_tomado' in processos_inclusos,
                    'provided': 'rel_prestado' in processos_inclusos,
                    'nfe_taken': 'nfe_tomado' in processos_inclusos,
                    'nfe_provided': 'nfe_prestado' in processos_inclusos
                }

                t = threading.Thread(target=callExec,
                                     name=f"{codigo_unico}",
                                     args=(idAgendamento, listaParametros, idCidUF)  # Ordem correta dos argumentos
                                     )
                t.start()


def agendamentoAddSchenduler(agendamentoID):
    with app.app_context():
        agendamento = AgendamentosRPA.query.filter_by(id=agendamentoID).first()
        empresaAgendamento = Empresas.query.filter_by(id=agendamento.id_empresa).first()

        data = agendamento.data_primeiro_agendamento
        data = data.strptime(str(data), '%Y-%m-%d %H:%M:%S')
        data_day = data.day
        data_hour = data.hour
        data_min = data.minute
        if agendamento.in_repeat:
            scheduler.add_job(
                id=f'{agendamento.id}',
                func=chamaExec,
                args=(agendamento.id,),
                trigger='cron',
                day=data_day,
                hour=data_hour,
                minute=data_min,
                second=0,
                month='*',
                start_date=fuso_horario.localize(agendamento.data_primeiro_agendamento),
                end_date=empresaAgendamento.licensed_until
            )

        elif not agendamento.in_repeat:
            scheduler.add_job(
                id=f'{agendamento.id}',
                func=chamaExec,
                args=(agendamento.id,),
                trigger='date',
                run_date=agendamento.data_primeiro_agendamento,
            )

        dadosAgendamento = scheduler.get_job(job_id=f'{agendamento.id}')
        with app.app_context():
            agendamentoStatus = AgendamentosRPA.query.filter_by(id=agendamento.id).first()
            try:
                agendamentoStatus.job_trigger = f"{dadosAgendamento.trigger}"
                db.session.commit()
            except Exception:
                ''

        print(f"- ID: {agendamento.id} | Empresa: {empresaAgendamento.nome}")


def carregarAgendamentosAnteriores():
    print('-== Carregando agendamentos prévios! ==-')
    with app.app_context():
        try:
            AgendamentosGerais = AgendamentosRPA.query.all()
            print('- Lista de Agendamentos -')
        except Exception:
            AgendamentosGerais = []
            print('Agendamentos Prévios Inexistentes')

        for agendamento in AgendamentosGerais:
            empresaAgendamento = Empresas.query.filter_by(id=agendamento.id_empresa).first()

            data = agendamento.data_primeiro_agendamento
            data = data.strptime(str(data), '%Y-%m-%d %H:%M:%S')
            data_day = data.day
            data_hour = data.hour
            data_min = data.minute
            if agendamento.in_repeat:
                scheduler.add_job(
                    id=f'{agendamento.id}',
                    func=chamaExec,
                    args=(agendamento.id,),
                    trigger='cron',
                    day=data_day,
                    hour=data_hour,
                    minute=data_min,
                    second=0,
                    month='*',
                    start_date=fuso_horario.localize(agendamento.data_primeiro_agendamento),
                    end_date=empresaAgendamento.licensed_until
                )

            elif not agendamento.in_repeat:
                scheduler.add_job(
                    id=f'{agendamento.id}',
                    func=chamaExec,
                    args=(agendamento.id,),
                    trigger='date',
                    run_date=agendamento.data_primeiro_agendamento,
                )

            dadosAgendamento = scheduler.get_job(job_id=f'{agendamento.id}')
            agendamentoStatus = AgendamentosRPA.query.filter_by(id=agendamento.id).first()
            try:
                agendamentoStatus.job_trigger = f"{dadosAgendamento.trigger}"
                db.session.commit()
            except Exception:
                ''

            print(f"- ID: {agendamento.id} | Empresa: {empresaAgendamento.nome}")
    print('-== Agendamentos Carregados! ==-')
