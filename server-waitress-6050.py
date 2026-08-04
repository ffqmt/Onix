import atexit
from waitress import serve
from onix import app, scheduler, carregarAgendamentosAnteriores
from flask_cors import CORS

if __name__ == "__main__":
    try:


        carregarAgendamentosAnteriores()
        scheduler.start()
        print('Servindo OnixWeb')
        serve(app, host='0.0.0.0', port=6556, threads=8)
        atexit.register(lambda: scheduler.shutdown())
    except Exception as e:
        print(f"Error occurred: {e}")
