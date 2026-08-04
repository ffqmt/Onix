import atexit
from waitress import serve
from onix import app, scheduler, carregarAgendamentosAnteriores

if __name__ == "__main__":
    try:
        carregarAgendamentosAnteriores()
        scheduler.start()
        print('Servindo OnixWeb')
        serve(app, host='0.0.0.0', port=5000, threads=8)
        atexit.register(lambda: scheduler.shutdown())
    except Exception as e:
        print(f"Error occurred: {e}")









