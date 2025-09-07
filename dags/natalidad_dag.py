#ESTE ES EL TRABAJADO CON LA API DEL BANCO MUNDIAL... QUEDA MUY LIMPIO Y MAS CORTO Y MODULAR QUE EL ANTERIOR...
#ADEMÁS FUE MAS FACIL REORDENAR LOS DATOS PORQUE DESCARGA EN JASON ASIQUE LE DAMOS ESTRUCTURA NOSOTROS...
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import pandas as pd
import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from airflow.models import Variable

#CREAMOS LA CONFIGURACIÓN NECESARIA
DATA_DIR = "/tmp/proyecto_datos"
FINAL_PATH = os.path.join(DATA_DIR, "processed/merged_dataset.csv")

# ACÁ ESCRIBIMOS LOS INDICADORES A DESCARGAR DEL BANCO MUNDIAL
INDICADORES = {
    "Natalidad": "SP.DYN.CBRT.IN",          # tasa bruta de natalidad
    "MortalidadInfantil": "SP.DYN.IMRT.IN", # mortalidad infantil
    "EsperanzaVida": "SP.DYN.LE00.IN",      # esperanza de vida al nacer
    "MortalidadMaterna": "SH.STA.MMRT"      # mortalidad materna
}

default_args = {
    'owner': 'Grupo_7_Ciencia_de_Datos',
    'start_date': datetime.today() - timedelta(days=1),
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
    'email_on_failure': False,
    'depends_on_past': False,
}

# DEFINIMOS LAS FUNCIONES QUE VAMOS A USAR

#DESCARGAMOS LOS INDICADORES QUE SELECCIONAMOS ARRIBA DESDE EL BANCO MUNDIAL
def download_indicators_wb(**kwargs):
   
    os.makedirs(os.path.join(DATA_DIR, "raw"), exist_ok=True)

    for nombre, codigo in INDICADORES.items():
        url = (
            f"https://api.worldbank.org/v2/country/all/indicator/{codigo}"
            "?date=2000:2023&format=json&per_page=20000"
        )
        print(f"[INFO] Estamos descargando {nombre} desde {url}")
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()[1]

        #COMO LOS DATOS ESTAN EN JSON VAMOS A ESTRUCTURARLOS
        df = pd.json_normalize(data)
        df = df.rename(columns={
            "country.value": "Pais",
            "country.id": "CodigoPais",
            "date": "Año",
            "value": nombre
        })

        output_file = os.path.join(DATA_DIR, "raw", f"{nombre}.csv")
        df.to_csv(output_file, index=False)
        print(f"[INFO] {nombre} guardado en {output_file}")

#LA FUNCION MERGE USARÁ LOS CSV DESCARGADOS PARA CADA INDICADOR
#LIMPIA LAS FILAS SIN VALORES
#VAMOS A PODER FILTRAR POR PAISES ESPECIFICOS O DE TODO EL MUNDO
def merge_indicators(**kwargs):
    """
    Mergea los CSV descargados de cada indicador, limpia filas sin valores,
    filtra por países específicos y guarda el CSV final.
    
    kwargs:
        paises (list): lista de países a incluir. Si es None, incluye todos.
    """
    paises = kwargs.get("paises", None)  # Lista de países a filtrar (opcional)

    dfs = []
    for nombre in INDICADORES.keys():
        file_path = os.path.join(DATA_DIR, "raw", f"{nombre}.csv")
        df = pd.read_csv(file_path)
        dfs.append(df[["Pais", "CodigoPais", "Año", nombre]])

    # REALIZAMOS UN MERGE SECUENCIAL PARA LOS INDICADORES
    df_merged = dfs[0]
    for df in dfs[1:]:
        df_merged = df_merged.merge(df, on=["Pais", "CodigoPais", "Año"], how="outer")

    # PODEMOS ELIMINAR LAS FILAS QUE NO TENGAN UN VALOR VÁLIDO CON ESTA LINEA DE CODIGO
    #df_merged = df_merged.dropna(subset=list(INDICADORES.keys()), how="all")

    #PODEMOS FILTRAR POR PAISES SI QUEREMOS O BIEN TODOS LOS PAISES
    if paises:
        df_merged = df_merged[df_merged["Pais"].isin(paises)]

    #REORDENAMOS COLUMNAS
    cols = ["Año", "Pais", "CodigoPais"] + list(INDICADORES.keys())
    df_merged = df_merged[cols]

    # GUARDAMOS EL CSV FINAL
    os.makedirs(os.path.dirname(FINAL_PATH), exist_ok=True)
    df_merged.to_csv(FINAL_PATH, index=False)
    print(f"[INFO] CSV final generado en {FINAL_PATH} para los países: {paises if paises else 'Todos'}")

#ESTA FUNCIÓN PERMITE ENVIAR EL CSV A UN CORREO
def enviar_correo(**kwargs):

    smtp_user = Variable.get("SMTP_USER")   
    smtp_password = Variable.get("SMTP_PASSWORD") 
    destinatario = "jonatan4731@outlook.com" 

    asunto = "Dataset Final - Proyecto Ciencia de Datos"
    cuerpo = "Hola!\n\nEcontrarás adjunto el CSV generado desde airflow con la API del Banco Mundial.\n\nSaludos!"

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = destinatario
    msg["Subject"] = asunto
    msg.attach(MIMEText(cuerpo, "plain"))

    with open(FINAL_PATH, "rb") as adjunto:
        parte = MIMEBase("application", "octet-stream")
        parte.set_payload(adjunto.read())
        encoders.encode_base64(parte)
        parte.add_header("Content-Disposition", f"attachment; filename={os.path.basename(FINAL_PATH)}")
        msg.attach(parte)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, destinatario, msg.as_string())

    print(f"[INFO] El correo fue enviado a {destinatario} con el archivo {FINAL_PATH}")


# AHORAS ARMAMOS EL DAG
with DAG(
    dag_id="Proyecto_airflow_Ciencia_de_Datos",
    description="Descarga y procesamiento de indicadores del Banco Mundial, filtrando países y enviando CSV",
    default_args=default_args,
    schedule=None,
    catchup=False,
    tags=["Banco Mundia", "indicadores", "natalidad", "mortalidad", "esperanza_vida"],
) as dag:

    descargar_indicadores = PythonOperator(
        task_id="descargar_indicadores",
        python_callable=download_indicators_wb,
    )

    merge_datos = PythonOperator(
        task_id="merge_indicadores",
        python_callable=merge_indicators,
        #LA SIGUIENTE LÍNEA DE CODIGO POERMITE FILTRAR POR PAISES
        # op_kwargs={"paises": ["Argentina", "Brasil", "Chile"]},  # Filtra solo estos países
    )

    enviar_mail_task = PythonOperator(
        task_id="enviar_mail",
        python_callable=enviar_correo,
    )

    descargar_indicadores >> merge_datos >> enviar_mail_task
