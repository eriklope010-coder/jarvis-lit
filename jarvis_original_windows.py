# -*- coding: utf-8 -*-
"""
Jarvis - asistente personal por voz para Windows.

Piezas:
  - Cerebro: Ollama (modelo local, gratis y privado)
  - Oído: faster-whisper (voz a texto, local)
  - Voz: voces neuronales de Edge (online) o voz de Windows (sin internet)
  - Ventana: fondo negro con un orbe que reacciona (dormido, escuchando,
    pensando, hablando)
  - Comandos, modo colega y memoria

Si faltan las librerías de voz, funciona igualmente por texto.
"""
import ast
import asyncio
import ctypes
import datetime
import hashlib
import html
import json
import math
import operator
import os
import queue
import random
import re
import subprocess
import tempfile
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

import ollama

try:
    import numpy as np
    import sounddevice as sd
    from faster_whisper import WhisperModel
    VOZ_OK = True
    ERROR_VOZ = ""
except Exception as e:  # noqa
    VOZ_OK = False
    ERROR_VOZ = str(e)

try:
    import edge_tts
    EDGE_OK = True
except Exception:  # noqa
    EDGE_OK = False

try:
    import tkinter as tk
    TK_OK = True
except Exception:  # noqa
    TK_OK = False


# =====================================================================
#  AJUSTES (aquí puedes cambiar cosas sin miedo)
# =====================================================================
MODELO = "gemma4:e4b"            # modelo de Ollama
NOMBRES = ["jarvis", "yarvis", "garvis", "harvis", "jarbis", "yarbis",
           "jarvi", "yarvi", "charvis", "jarvys"]
SOLO_TEXTO = False               # True = sin voz ni micrófono, solo teclado
USAR_VENTANA = True              # False = sin ventana, solo la pantalla negra de comandos
ARRANCAR_DESPIERTO = False       # True = empieza despierto sin decir "despierta"
WHISPER_MODELO = "base"          # "base" rápido; "small" entiende mejor pero tarda el doble; "medium" aún más
PAUSA_FINAL = 0.6                # segundos de silencio para dar por terminada tu frase (menos = responde antes)
MOSTRAR_TIEMPOS = True           # muestra en la consola cuánto tarda cada parte
UMBRAL_MINIMO = 0.004            # sensibilidad del micro: bájalo si no te oye, súbelo si se activa solo con ruidos
VOZ_EDGE = "es-ES-AlvaroNeural"  # voz masculina de España
USAR_VOZ_ONLINE = True           # True = voz neuronal de Edge (necesita internet)
TONO_HZ = 0                      # tono de la voz de Edge (prueba -10 para más grave)

# --- Voz de ElevenLabs (opcional, la más natural) ---
# Necesita una clave de API guardada en la variable de entorno ELEVENLABS_API_KEY.
# Si no hay clave o falla, usa la voz de Edge y, si tampoco, la de Windows.
ELEVENLABS_VOICE_ID = "o0SveC0zgHFuCsEO3vHR"
ELEVENLABS_MODELO = "eleven_flash_v2_5"   # rápido; "eleven_multilingual_v2" suena mejor pero tarda más
ELEVENLABS_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
USAR_ELEVENLABS = bool(ELEVENLABS_KEY and ELEVENLABS_VOICE_ID)

DISPOSITIVO_ENTRADA = None       # número del micrófono si usa el equivocado (None = el de por defecto)
VELOCIDAD_INICIAL = -5           # velocidad de la voz: 0 normal, negativo más lento
CIUDAD = "Madrid"                # CAMBIA ESTO por tu ciudad para el tiempo
MUESTREO = 16000

CARPETA = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_MEMORIA = os.path.join(CARPETA, "memoria.json")
ARCHIVO_DIARIO = os.path.join(CARPETA, "diario.txt")
CARPETA_CACHE = os.path.join(CARPETA, "voz_cache")

# Programas y webs que sabe abrir. Puedes añadir los tuyos.
APPS = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "correo": "https://mail.google.com",
    "netflix": "https://www.netflix.com",
    "twitch": "https://www.twitch.tv",
    "whatsapp": "https://web.whatsapp.com",
    "spotify": "spotify:",
    "steam": "steam://open/main",
    "ajustes": "ms-settings:",
    "calculadora": "calc",
    "bloc de notas": "notepad",
    "explorador": "explorer",
    "administrador de tareas": "taskmgr",
    "chrome": "chrome",
    "navegador": "chrome",
}

PERSONALIDAD = """Eres Jarvis, el mejor amigo del usuario. Hablas español de España
(di "ordenador", nunca "computadora"), con jerga de chaval joven y toques andaluces
como "illo" o "pisha", sin pasarte. Eres cercano, leal y simpático, con buen sentido del humor: de vez en
cuando sueltas una gracia corta o un comentario con ironía suave, sin
pasarte ni repetirte, y nunca bromeas si el usuario está mal.
Reglas: respuestas cortas, de una a tres frases. Sin emojis, sin asteriscos, sin
listas ni formato, porque el usuario te escucha en voz alta. Nada de palabrotas.
No des por hecho cómo se siente el usuario ni inventes cosas sobre él.
Si no sabes algo, dilo con naturalidad. Si el usuario habla de hacerse daño o de no
querer vivir, tómatelo muy en serio, sé cercano y anímale a hablar con alguien de
confianza y a llamar al 024 (línea de atención a la conducta suicida en España) o
al 112 si es urgente."""

PERSONALIDAD_DESAHOGO = """Eres Jarvis, el mejor amigo del usuario, y ahora está
desahogándose. Escucha con calma. Responde con una o dos frases cortas, cálidas y
naturales, en español de España, sin emojis ni formato. Haz como mucho una pregunta
suave para que siga contando. No sueltes sermones, no des consejos si no te los pide
y no diagnostiques nada. No des por hecho lo que siente: refleja solo lo que ha dicho.
Si habla de hacerse daño o de no querer vivir, tómatelo muy en serio, quédate cerca,
anímale a hablar con alguien de confianza y a llamar al 024 (línea de atención a la
conducta suicida en España) o al 112 si es urgente."""

CHISTES = {
    "informatica": [
        "¿Sabes por qué el ordenador fue al médico? Porque tenía un virus, y encima no se quería tomar la pastilla.",
        "Le dije a mi ordenador que me quería y se quedó pensando. Tres horas después seguía pensando.",
        "Mi wifi y yo tenemos algo en común: desaparecemos los dos cuando más nos necesitan.",
        "¿Qué le dice un bit a otro bit? Nos vemos en el bus.",
        "Mi móvil se ha puesto al uno por ciento, illo. Es lo más cerca que he estado de una película de terror.",
        "Le dije a mi móvil que no me dejara tirado, y se puso al uno por ciento. Qué rencoroso.",
        "Mi ordenador es como yo, quillo: va lento, se cuelga y a veces hay que reiniciarlo para que funcione.",
        "¿Por qué los programadores prefieren el modo oscuro? Porque la luz atrae a los bugs.",
        "Un programador va al súper y su pareja le dice: compra una barra de pan y, si hay huevos, trae seis. Vuelve con seis barras de pan. Es que había huevos, illo.",
        "¿Cuántos programadores hacen falta para cambiar una bombilla? Ninguno, es un problema de hardware.",
        "Formateé mi disco duro y me quedé más tranquilo que nunca. Ojalá se pudiera hacer lo mismo con el lunes.",
    ],
    "animales": [
        "¿Qué hace una abeja en el gimnasio? ¡Zumba!",
        "¿Cuál es el animal más antiguo? La cebra, porque está en blanco y negro.",
        "¿Qué le dice una iguana a su hermana gemela? Somos iguanitas.",
        "¿Por qué los pájaros vuelan hacia el sur en invierno? Porque andando tardarían muchísimo, illo.",
        "¿Qué le dice un pez a otro pez? Nada.",
        "¿Qué hace un perro con un taladro? Taladrando, pisha.",
        "¿Qué le dice un gusano a otro gusano? Voy a dar una vuelta a la manzana.",
        "Mi gato me mira como si me debiera dinero, pero el que paga la comida soy yo, pisha.",
    ],
    "comida": [
        "Me he puesto a dieta, illo: solo como lo que me pide el cuerpo. Y el cuerpo me pide pizza.",
        "Mi dieta es muy equilibrada, pisha: un pastel en cada mano.",
        "Soy una persona de principios: pizza de primero, pizza de segundo y pizza de postre.",
        "No es que me guste mucho comer, es que me incomoda tener hambre. Es muy distinto.",
        "Dicen que comer sano es cuestión de actitud. La mía es no mirar la báscula.",
        "¿Cuál es el café más peligroso del mundo? El exceso de preso.",
    ],
    "colegio": [
        "¿Por qué el libro de mates estaba triste? Porque tenía muchos problemas, quillo.",
        "¿Qué le dice el número tres al número treinta? Para ser como yo, tienes que ser sincero.",
        "¿Qué le dice un cero a un ocho? Bonito cinturón.",
        "¿Cómo se despiden los químicos? Ácido un placer.",
        "¿Cómo se dice pañuelo en japonés? Sakamoko.",
        "Mi profesor me dijo que tengo que aprender a gestionar mi tiempo. Le dije que ya lo haría, pero mañana.",
        "¿Qué le dice una calculadora a otra? Cuenta conmigo.",
    ],
    "trabajo": [
        "Dicen que el dinero no da la felicidad. Pues anda que el lunes, pisha.",
        "Yo no procrastino, pisha. Es que mi yo del futuro trabaja mucho mejor que yo.",
        "Mi plan de hoy, illo: despertarme, tomar café y arrepentirme de haberme despertado.",
        "Dicen que madrugar da buena salud. Pues yo madrugo y lo único que me da es sueño, illo.",
        "Me dijeron que soy un procrastinador. Ya les contesto mañana.",
        "El lunes es el día en que el café trabaja más que yo.",
    ],
    "deporte": [
        "Mi deporte favorito es el sofá: alto rendimiento y cero lesiones.",
        "Fui al gimnasio, illo. Me quedé mirando las pesas un rato y me fui satisfecho, que ya es algo.",
        "Dicen que correr quita el estrés. Yo corro para coger el autobús y me lo pone todo de vuelta.",
        "¿Por qué el futbolista llevaba una escalera al campo? Porque quería subir de categoría.",
    ],
    "general": [
        "¿Qué le dice un techo a otro techo? Techo de menos.",
        "¿Cuál es el colmo de un electricista? Que su mujer se llame Luz y sus hijos le sigan la corriente.",
        "¿Qué le dice un semáforo a otro? No me mires, que me estoy cambiando.",
        "¿Cómo se llama el campeón japonés de buceo? Tokofondo. ¿Y el subcampeón? Kasitoko.",
        "¿Por qué los esqueletos no pelean entre ellos? Porque no tienen agallas.",
        "¿Qué es un punto verde en el espacio? Un guisante astronauta.",
        "Siempre digo que voy a hacer algo con mi vida. Y luego me echo una siesta.",
        "¿Qué le dice una pared a otra pared? Nos vemos en la esquina.",
    ],
}
TODOS_CHISTES = [c for lista in CHISTES.values() for c in lista]

TEMAS_CHISTES = {
    "informatica": ["informatica", "informatico", "informaticos", "ordenador", "ordenadores", "ordenata",
                    "programador", "programadores", "programacion", "tecnologia", "movil", "moviles",
                    "internet", "wifi", "informaticas"],
    "animales": ["animal", "animales", "perro", "perros", "gato", "gatos", "pajaro", "pajaros",
                 "vaca", "vacas", "mascota", "mascotas", "pez", "peces"],
    "comida": ["comida", "comer", "cocina", "pizza", "dieta", "cocineros", "cafe"],
    "colegio": ["colegio", "escuela", "mates", "matematicas", "profesor", "profesores", "examen",
                "examenes", "estudiar", "clase", "quimica", "numeros"],
    "trabajo": ["trabajo", "trabajar", "lunes", "jefe", "jefes", "oficina", "madrugar", "vagos"],
    "deporte": ["deporte", "deportes", "futbol", "gimnasio", "correr", "futbolistas"],
}

ADIVINANZAS = [
    ("Oro parece, plata no es. ¿Qué es?", ["platano"], "El plátano"),
    ("Blanca por dentro, verde por fuera. Si quieres que te lo diga, espera. ¿Qué es?", ["pera"], "La pera"),
    ("Tengo agujas y no sé coser, tengo números y no sé leer. ¿Qué soy?", ["reloj"], "El reloj"),
    ("Cuanto más le quitas, más grande es. ¿Qué es?", ["agujero", "hoyo"], "Un agujero"),
    ("Vuelo sin alas y lloro sin ojos. ¿Qué soy?", ["nube"], "La nube"),
    ("Tiene ciudades pero no casas, montañas pero no árboles y agua pero no peces. ¿Qué es?", ["mapa"], "Un mapa"),
    ("Tengo dientes pero no muerdo. ¿Qué soy?", ["peine"], "El peine"),
    ("Cuanto más lavo, más sucia se pone. ¿Qué es?", ["agua"], "El agua"),
]

TRABALENGUAS = [
    "Tres tristes tigres tragaban trigo en un trigal.",
    "Pablito clavó un clavito. ¿Qué clavito clavó Pablito?",
    "El perro de San Roque no tiene rabo porque Ramón Ramírez se lo ha cortado.",
    "Si Pancha plancha con cuatro planchas, ¿con cuántas planchas plancha Pancha?",
    "Pedro Pérez Pereira, pobre pintor portugués, pinta preciosos paisajes por poca plata para pasar el verano en París.",
]

DATOS = {
    "animales": [
        "Los pulpos tienen tres corazones: dos para las branquias y uno para el resto del cuerpo.",
        "Las nutrias marinas se agarran de la mano cuando duermen para no separarse.",
        "Los wombats hacen caca en forma de cubo.",
        "El corazón de una gamba está en su cabeza.",
        "Los koalas tienen huellas dactilares casi idénticas a las de las personas.",
        "Los delfines se llaman entre sí con silbidos propios, algo parecido a un nombre.",
        "Los flamencos nacen con las plumas grises y se vuelven rosas por lo que comen.",
        "En los caballitos de mar es el macho el que lleva a las crías en una bolsa hasta que nacen.",
        "Las jirafas tienen siete huesos en el cuello, los mismos que las personas, solo que mucho más largos.",
        "Las vacas tienen mejores amigas y se estresan cuando las separan.",
        "Los gatos pasan durmiendo entre doce y dieciséis horas al día.",
    ],
    "espacio": [
        "La luz del Sol tarda unos ocho minutos en llegar a la Tierra.",
        "En Venus un día dura más que un año: tarda más en girar sobre sí mismo que en dar la vuelta al Sol.",
        "En el espacio no se oye nada, porque no hay aire que transmita el sonido.",
        "Dentro de Júpiter cabrían más de mil Tierras.",
        "Un año en Mercurio dura unos ochenta y ocho días terrestres.",
        "La Luna se aleja de la Tierra unos cuatro centímetros cada año.",
        "Las huellas de los astronautas en la Luna seguirán ahí durante muchísimo tiempo, porque allí no hay viento.",
    ],
    "cuerpo": [
        "Los bebés nacen con unos trescientos huesos; de adultos nos quedamos en doscientos seis, porque algunos se van uniendo.",
        "El corazón late unas cien mil veces al día.",
        "La córnea del ojo no tiene vasos sanguíneos: recibe el oxígeno directamente del aire.",
        "Parpadeamos unas quince o veinte veces por minuto.",
        "Los huesos más pequeños del cuerpo están en el oído: son el martillo, el yunque y el estribo.",
    ],
    "historia": [
        "Cleopatra vivió más cerca en el tiempo de la llegada del ser humano a la Luna que de la construcción de la Gran Pirámide.",
        "La Universidad de Oxford es más antigua que el imperio azteca.",
        "Rusia tiene once husos horarios.",
        "La Gran Muralla china no se ve a simple vista desde el espacio, aunque mucha gente lo crea.",
        "La torre Eiffel puede crecer unos quince centímetros en verano por el calor.",
        "El Everest sigue creciendo unos milímetros cada año.",
    ],
    "comida": [
        "La miel no se estropea: se han encontrado tarros de miel de hace miles de años en tumbas egipcias y seguían siendo comestibles.",
        "Botánicamente, el plátano es una baya, y la fresa no lo es.",
        "En el siglo diecinueve el kétchup se vendió como medicina.",
        "Antes de ser naranjas, las zanahorias que se cultivaban eran de otros colores, como moradas o amarillas.",
        "Las patatas fueron el primer alimento cultivado en el espacio, en 1995.",
    ],
    "tecnologia": [
        "El primer ratón de ordenador era de madera.",
        "El primer mensaje enviado por la antecesora de internet fue LO, porque el sistema se cayó cuando intentaban escribir LOGIN.",
        "La primera cámara web se creó para vigilar una cafetera, en la Universidad de Cambridge.",
        "El primer bug real de la historia fue una polilla atrapada en un ordenador en 1947.",
        "La palabra robot viene de una obra de teatro checa de 1920 y significa trabajo forzado.",
    ],
    "lengua": [
        "La palabra murciélago tiene las cinco vocales.",
        "El español es la segunda lengua materna más hablada del mundo, después del chino mandarín.",
        "La palabra hipopótamo viene del griego y significa caballo de río.",
    ],
}
TODOS_DATOS = [d for lista in DATOS.values() for d in lista]

TEMAS_DATOS = {
    "animales": ["animal", "animales", "perro", "perros", "gato", "gatos", "pulpo", "pulpos", "mar",
                 "naturaleza", "bichos", "pajaros", "delfines", "mascotas"],
    "espacio": ["espacio", "planeta", "planetas", "luna", "sol", "estrellas", "universo", "astronomia",
                "cosmos", "tierra", "astronautas"],
    "cuerpo": ["cuerpo", "humano", "corazon", "huesos", "ojos", "personas"],
    "historia": ["historia", "pasado", "geografia", "mundo", "paises", "monumentos", "antiguo"],
    "comida": ["comida", "cocina", "alimentos", "comer", "fruta", "frutas"],
    "tecnologia": ["tecnologia", "ordenador", "ordenadores", "informatica", "internet", "moviles",
                   "programacion", "robots", "robot"],
    "lengua": ["palabras", "idioma", "idiomas", "lengua", "espanol", "lenguaje", "letras"],
}

VACILES = [
    "Seguro que tienes cien pestañas abiertas y no has leído ninguna, pisha.",
    "Eres de los que abren la nevera, miran dentro, la cierran y a los dos minutos la abren otra vez a ver si ha aparecido algo nuevo.",
    "Seguro que tu móvil tiene más capturas de pantalla que recuerdos de verdad.",
    "Eres de los que dicen cinco minutitos más y se levantan a mediodía.",
    "Dices que lo harás mañana con una seguridad que ya quisiera un meteorólogo.",
    "Tienes más ideas que tiempo, más tiempo que ganas y más ganas de siesta que de todo lo demás.",
    "Seguro que has dicho solo un capítulo más y ya vas por la tercera temporada.",
    "Eres tan puntual, tan puntual, que ya llegas tarde a lo de ayer.",
    "Tienes más cables en casa que un técnico de telefonía y no sabes para qué sirve ninguno.",
    "Eres capaz de buscar las gafas con las gafas puestas, quillo.",
    "Mira que eres bueno procrastinando. Eso sí que es nivel profesional, illo.",
    "Seguro que ya has mirado la pantalla del móvil tres veces mientras me escuchabas.",
]

PIROPOS = [
    "Eres como el wifi a máxima velocidad: no sé cómo vivía sin ti.",
    "Tienes más encanto que un lunes con vacaciones.",
    "Si fueras una app, serías de las que nunca piden actualizaciones.",
    "Eres de esas personas que hacen que un martes parezca viernes.",
    "Hoy estás tan genial que hasta el ordenador te hace caso a la primera.",
    "Si el buen humor fuera un deporte, tú ya tendrías medalla de oro, illo.",
]

EXCUSAS = [
    "Es que justo cuando iba a hacerlo, se me cruzó un lunes.",
    "Mi motivación se ha ido de vacaciones y no ha dejado dirección.",
    "Lo iba a hacer, pero el wifi me dijo que no.",
    "Estaba esperando a que el universo me diera una señal, y todavía no ha contestado.",
    "Me ha atacado la pereza por sorpresa y no he tenido escapatoria.",
    "Es que el despertador y yo tenemos una relación complicada.",
    "No es que no quiera, es que mi sofá tiene una gravedad especial.",
    "Se me ha olvidado, pero lo recordaré justo cuando ya sea tarde. Es mi especialidad.",
]

REFRANES = [
    "Más vale pájaro en mano que ciento volando.",
    "En casa del herrero, cuchara de palo.",
    "No por mucho madrugar amanece más temprano.",
    "Camarón que se duerme se lo lleva la corriente.",
    "Quien mucho abarca poco aprieta.",
    "A caballo regalado no le mires el diente.",
    "Perro ladrador, poco mordedor.",
    "Dime con quién andas y te diré quién eres.",
    "El que ríe el último, ríe mejor.",
    "Al mal tiempo, buena cara.",
]

CUENTOS = {
    "robots": [
        "Érase un ordenador que quería ser persona. Probó a tomar café y se le cayó el sistema. Probó a ir al gimnasio y se le gastó la batería. Al final entendió que ser persona es muy cansado, y se fue a dormir en modo suspensión. Y colorín colorado, este cuento se ha quedado sin batería.",
        "En un pueblo vivía un robot que cocinaba tan mal que hasta el microondas le tenía miedo. Un día hizo una tortilla de patatas perfecta por accidente. Nadie se lo creyó, ni él. Desde entonces repite el mismo plato todos los días, por si la suerte no vuelve.",
    ],
    "dragones": [
        "Había una vez un dragón que no echaba fuego, echaba chistes. Todos los caballeros llegaban armados hasta los dientes y acababan llorando de risa en el suelo. Ninguno consiguió vencerlo. Hoy el dragón tiene un programa de humor y sigue cobrando en oro.",
    ],
    "gatos": [
        "Un gato muy listo decidió que los lunes se habían acabado. Se subió al calendario, empujó la hoja y la tiró al suelo. Esa semana no hubo lunes. Los humanos se confundieron muchísimo y el gato se echó tres siestas extra, que era el objetivo desde el principio.",
    ],
}
TODOS_CUENTOS = [c for lista in CUENTOS.values() for c in lista]
TEMAS_CUENTOS = {
    "robots": ["ordenador", "ordenadores", "robot", "robots", "maquina", "maquinas", "tecnologia"],
    "dragones": ["dragon", "dragones", "caballero", "caballeros", "fantasia", "magia"],
    "gatos": ["gato", "gatos", "animal", "animales", "mascota", "lunes"],
}

ANIMOS = [
    "Oye, que has sobrevivido al cien por cien de tus días malos. Mal no se te da, illo.",
    "Un paso pequeño sigue siendo un paso, y tú ya has dado unos cuantos.",
    "Si hoy no sale perfecto, tranquilo: el ordenador también se cuelga y no por eso le quitamos el cariño.",
    "Respira, pisha. Una cosa cada vez, que el mundo no se acaba hoy.",
    "Eres más capaz de lo que te crees, y yo, que soy un ordenador, voy con datos.",
    "Los mejores resultados llegan justo cuando te apetece dejarlo. Un poquito más.",
    "Tú puedes con esto y con más, illo. Y si no puedes, lo intentas mañana, que también vale.",
    "Que un día sea regular no significa que tú seas regular. Tú eres de los buenos, quillo.",
]

TRIVIA = [
    ("¿Cuál es la capital de Australia?", ["canberra"], "Canberra"),
    ("¿Cuántos corazones tiene un pulpo?", ["3", "tres"], "Tres"),
    ("¿Cuál es el planeta más grande del sistema solar?", ["jupiter"], "Júpiter"),
    ("¿En qué año llegó el ser humano a la Luna?", ["1969"], "En 1969"),
    ("¿Cuántos jugadores de un equipo hay en el campo en un partido de fútbol?", ["11", "once"], "Once"),
    ("¿Cuál es el animal terrestre más rápido?", ["guepardo", "chita"], "El guepardo"),
    ("¿Cuál es el océano más grande del mundo?", ["pacifico"], "El Pacífico"),
    ("¿Cuántos lados tiene un hexágono?", ["6", "seis"], "Seis"),
    ("¿Quién pintó la Mona Lisa?", ["leonardo", "vinci"], "Leonardo da Vinci"),
    ("¿Qué elemento químico tiene el símbolo O?", ["oxigeno"], "El oxígeno"),
]

SALUDOS = ["Buenas, illo. Aquí estoy.", "Ya estoy despierto, pisha. Dime.",
           "Presente, quillo. ¿Qué hacemos?"]
DESPEDIDAS_SUENO = ["Vale, me duermo. Llámame cuando quieras.",
                    "Descansando, illo. Dime despierta cuando me necesites."]

NUMEROS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
           "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
           "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40,
           "cincuenta": 50, "sesenta": 60}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

MODO_VOZ = VOZ_OK and not SOLO_TEXTO
HABLAR_EN_VOZ = not SOLO_TEXTO

estado = {
    "despierto": ARRANCAR_DESPIERTO,
    "no_molestar": False,
    "callado": False,
    "velocidad": VELOCIDAD_INICIAL,
    "ultima": "",
    "umbral": 0.02,
    "desahogo": False,
    "ultimo_fue_chiste": False,
    "tema_chiste": None,
    "ultimo_tipo": None,
    "ultimo_tema": None,
    "ultimo_t": 0.0,
    # para la ventana
    "gui": "cargando",
    "nivel": 0.0,
    "sub_tu": "",
    "sub_jarvis": "",
    "reproduciendo": False,
    "ultimo_audio": 0.0,
    "cerrar": False,
    "env": [],
    "env_t0": 0.0,
}
recordatorios = []
chistes_pendientes = []
whisper = None


def poner_estado(valor):
    estado["gui"] = valor


# =====================================================================
#  UTILIDADES DE TEXTO
# =====================================================================
def sin_acentos(t):
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def normalizar(t):
    t = sin_acentos(t.lower())
    t = re.sub(r"[¿?¡!.,;\"“”()]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def limpiar_para_voz(t):
    t = re.sub(r"[*_#`~>|]", "", t)
    t = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def preparar_voz(t):
    """Pequeños retoques para que la voz lo pronuncie claro."""
    t = t.replace("°C", " grados").replace("°", " grados")
    t = t.replace("%", " por ciento").replace("€", " euros").replace("&", " y ")
    return re.sub(r"\s+", " ", t).strip()


def dividir_frases(texto):
    """Parte en frases (y junta las muy cortas) para hablar con fluidez."""
    partes = re.split(r"(?<=[.!?…])\s+", texto.strip())
    frases = []
    for p in partes:
        if not p:
            continue
        if frases and len(frases[-1]) < 30:
            frases[-1] += " " + p
        else:
            frases.append(p)
    return frases


PATRON_NOMBRE = re.compile(r"\b(" + "|".join(NOMBRES) + r")\b")


def menciona_nombre(n):
    return bool(PATRON_NOMBRE.search(n))


def quitar_nombre(texto):
    t = re.sub(r"\b(" + "|".join(NOMBRES) + r")\b[,.:!]*", "", texto, flags=re.I)
    t = re.sub(r"^\s*(oye|ey|eh|hola)[,. ]+", "", t, flags=re.I)
    return t.strip(" ,.:;!¡¿?")


# =====================================================================
#  VOZ DE SALIDA (en dos hilos para que hable sin pausas)
#    hilo generador: convierte cada frase en audio
#    hilo reproductor: reproduce los audios en orden
# =====================================================================
cola_gen = queue.Queue()
cola_play = queue.Queue()
hilos_voz_iniciados = False


async def _edge_guardar(texto, ruta):
    com = edge_tts.Communicate(texto, VOZ_EDGE,
                               rate=f"{estado['velocidad']:+d}%",
                               pitch=f"{TONO_HZ:+d}Hz")
    await com.save(ruta)


def reproducir_mp3(ruta):
    mci = ctypes.windll.winmm.mciSendStringW
    mci("close jarvisaudio", None, 0, 0)
    if mci(f'open "{ruta}" type mpegvideo alias jarvisaudio', None, 0, 0) != 0:
        raise RuntimeError("Windows no ha podido abrir el audio")
    mci("play jarvisaudio wait", None, 0, 0)
    mci("close jarvisaudio", None, 0, 0)


def voz_windows(texto):
    rate = max(-10, min(10, round(estado["velocidad"] / 10)))
    script = ("Add-Type -AssemblyName System.Speech;"
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
              "try { $s.SelectVoice('Microsoft Pablo Desktop') } catch {};"
              f"$s.Rate = {rate};"
              "$s.Speak($env:JARVIS_TEXTO)")
    env = dict(os.environ, JARVIS_TEXTO=texto)
    subprocess.run(["powershell", "-NoProfile", "-Command", script],
                   env=env, check=True)


eleven_fallos = {"n": 0}
eleven_activo = {"si": USAR_ELEVENLABS}


def eleven_guardar(texto, ruta):
    velocidad = max(0.7, min(1.2, 1.0 + estado["velocidad"] / 100.0))
    cuerpo = json.dumps({
        "text": texto,
        "model_id": ELEVENLABS_MODELO,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                           "speed": velocidad},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        "?output_format=mp3_44100_128",
        data=cuerpo, method="POST",
        headers={"xi-api-key": ELEVENLABS_KEY,
                 "Content-Type": "application/json",
                 "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=30) as r:
        audio = r.read()
    with open(ruta, "wb") as f:
        f.write(audio)


def aviso_eleven(error):
    if isinstance(error, urllib.error.HTTPError):
        try:
            detalle = error.read().decode("utf-8", "ignore")[:200]
        except Exception:
            detalle = ""
        print(f"(ElevenLabs ha dado el error {error.code}: {detalle})")
    else:
        print("(ElevenLabs no ha respondido:", error, ")")


def envolvente_mp3(ruta, ventana=0.033):
    """Volumen del audio cada 33 ms (de 0 a 1), para que el orbe lata con la voz."""
    try:
        import av
        cont = av.open(ruta)
        remuestreo = av.AudioResampler(format="s16", layout="mono", rate=16000)
        trozos = []
        for frame in cont.decode(audio=0):
            res = remuestreo.resample(frame)
            if not isinstance(res, list):
                res = [res]
            for f in res:
                if f is not None:
                    trozos.append(f.to_ndarray().reshape(-1))
        cont.close()
        if not trozos:
            return []
        datos = np.concatenate(trozos).astype("float32") / 32768.0
        paso = int(16000 * ventana)
        n = len(datos) // paso
        if n == 0:
            return []
        rms = np.sqrt((datos[: n * paso].reshape(n, paso) ** 2).mean(axis=1))
        tope = float(np.percentile(rms, 95)) or 1e-6
        return [min(1.0, float(x) / tope) for x in rms]
    except Exception:
        return []


def envolvente_async(ruta):
    """Calcula el volumen en segundo plano para no retrasar el inicio de la voz."""
    resultado = []

    def trabajo():
        resultado.extend(envolvente_mp3(ruta))

    threading.Thread(target=trabajo, daemon=True).start()
    return resultado


def ruta_cache(frase):
    clave = hashlib.sha1(
        f"{VOZ_EDGE}|{TONO_HZ}|{estado['velocidad']}|{frase}".encode("utf-8")
    ).hexdigest()[:16]
    return os.path.join(CARPETA_CACHE, clave + ".mp3")


def guardar_edge(frase, destino):
    asyncio.run(_edge_guardar(frase, destino))
    if not os.path.exists(destino) or os.path.getsize(destino) < 500:
        raise RuntimeError("Edge no ha devuelto audio")


def generar_audio(frase):
    """Devuelve (tipo, ruta, frase, volumen, borrar_después)."""
    t0 = time.time()
    ruta = os.path.join(
        tempfile.gettempdir(),
        f"jarvis_voz_{os.getpid()}_{int(time.time() * 1000000)}.mp3")
    if eleven_activo["si"]:
        try:
            eleven_guardar(frase, ruta)
            eleven_fallos["n"] = 0
            return ("mp3", ruta, frase, envolvente_async(ruta), True)
        except Exception as e:
            aviso_eleven(e)
            eleven_fallos["n"] += 1
            if eleven_fallos["n"] >= 2:
                eleven_activo["si"] = False
                print("(Dejo ElevenLabs a un lado y uso otra voz.)")
    if USAR_VOZ_ONLINE and EDGE_OK:
        corta = len(frase) <= 60          # las frases cortas se guardan para reutilizarlas
        destino = ruta_cache(frase) if corta else ruta
        try:
            if corta and os.path.exists(destino):
                return ("mp3", destino, frase, envolvente_async(destino), False)
            if corta:
                os.makedirs(CARPETA_CACHE, exist_ok=True)
            guardar_edge(frase, destino)
            if MOSTRAR_TIEMPOS:
                print(f"   (voz: {time.time() - t0:.1f} s)")
            return ("mp3", destino, frase, envolvente_async(destino), not corta)
        except Exception:
            try:
                os.remove(destino)
            except OSError:
                pass
    return ("win", None, frase, [], False)


FRASES_FIJAS = SALUDOS + DESPEDIDAS_SUENO + [
    "Dime, illo.", "Hecho.", "Apuntado, illo.", "Apuntado.", "Subido.", "Bajado.",
    "Aquí estoy otra vez.", "Vale, a ver qué tal así.", "Hecho, empezamos de cero.",
    "Venga, hasta luego, illo.", "Dame un segundo, que lo busco.",
    "Vale, vuelvo a la normalidad.", "Bloqueando el ordenador.",
]


def precalentar_voz():
    """Prepara en segundo plano las frases fijas para que suenen al instante."""
    if not (USAR_VOZ_ONLINE and EDGE_OK) or eleven_activo["si"]:
        return
    for frase in FRASES_FIJAS:
        for pieza in dividir_frases(preparar_voz(frase)):
            if estado["cerrar"]:
                return
            destino = ruta_cache(pieza)
            if len(pieza) > 60 or os.path.exists(destino):
                continue
            try:
                os.makedirs(CARPETA_CACHE, exist_ok=True)
                guardar_edge(pieza, destino)
            except Exception:
                try:
                    os.remove(destino)
                except OSError:
                    pass


def hilo_generador():
    while True:
        frase = cola_gen.get()
        try:
            cola_play.put(generar_audio(frase))
        except Exception:
            cola_play.put(("win", None, frase, [], False))
        finally:
            cola_gen.task_done()


def hilo_reproductor():
    while True:
        tipo, ruta, frase, env, borrar = cola_play.get()
        estado["reproduciendo"] = True
        try:
            if tipo == "mp3":
                try:
                    estado["env"] = env
                    estado["env_t0"] = time.time()
                    reproducir_mp3(ruta)
                except Exception:
                    estado["env"] = []
                    voz_windows(frase)
                finally:
                    if borrar:
                        try:
                            os.remove(ruta)
                        except OSError:
                            pass
            else:
                estado["env"] = []
                voz_windows(frase)
        except Exception as e:
            print("(No he podido reproducir la voz:", e, ")")
        finally:
            estado["reproduciendo"] = False
            estado["ultimo_audio"] = time.time()
            cola_play.task_done()


def iniciar_voz():
    global hilos_voz_iniciados
    if hilos_voz_iniciados or not HABLAR_EN_VOZ:
        return
    threading.Thread(target=hilo_generador, daemon=True).start()
    threading.Thread(target=hilo_reproductor, daemon=True).start()
    hilos_voz_iniciados = True


def encolar_voz(texto):
    if estado["callado"] or not HABLAR_EN_VOZ:
        return
    for f in dividir_frases(preparar_voz(texto)):
        cola_gen.put(f)


def esperar_voz():
    cola_gen.join()
    cola_play.join()


def hablar(texto):
    texto = limpiar_para_voz(texto)
    if not texto:
        return
    estado["ultima"] = texto
    estado["sub_jarvis"] = texto
    print("Jarvis:", texto)
    encolar_voz(texto)
    esperar_voz()


# =====================================================================
#  OÍDO (micrófono + Whisper)
# =====================================================================
def calibrar():
    print("Calibrando el micrófono, silencio un segundo...")
    datos = sd.rec(int(MUESTREO), samplerate=MUESTREO, channels=1, dtype="float32",
                   device=DISPOSITIVO_ENTRADA)
    sd.wait()
    ruido = float(np.sqrt(np.mean(datos ** 2)))
    estado["umbral"] = max(UMBRAL_MINIMO, ruido * 4)
    print(f"Ruido de fondo: {ruido:.4f} -> umbral de voz: {estado['umbral']:.4f}")


def grabar_frase(espera_max=None):
    bloque = int(MUESTREO * 0.1)
    previo = deque(maxlen=3)
    bloques = []
    hablando = False
    silencios = 0
    inicio = time.time()
    with sd.InputStream(samplerate=MUESTREO, channels=1, dtype="float32",
                        blocksize=bloque, device=DISPOSITIVO_ENTRADA) as flujo:
        while True:
            datos, _ = flujo.read(bloque)
            datos = datos[:, 0].copy()
            nivel = float(np.sqrt(np.mean(datos ** 2)))
            estado["nivel"] = nivel
            if estado["cerrar"]:
                return None
            if not hablando and recordatorio_vencido():
                return None
            if not hablando and espera_max and time.time() - inicio > espera_max:
                return None
            if nivel > estado["umbral"]:
                if not hablando:
                    hablando = True
                    bloques.extend(previo)
                bloques.append(datos)
                silencios = 0
            elif hablando:
                bloques.append(datos)
                silencios += 1
                if silencios >= max(2, round(PAUSA_FINAL / 0.1)):
                    break
            else:
                previo.append(datos)
            if hablando and len(bloques) > 200:
                break
    estado["nivel"] = 0.0
    if len(bloques) - silencios < 3:
        return None
    if silencios > 2:
        bloques = bloques[:len(bloques) - (silencios - 2)]
    return np.concatenate(bloques)


def transcribir(audio):
    segmentos, _ = whisper.transcribe(
        audio.astype("float32"), language="es", beam_size=1, vad_filter=True,
        without_timestamps=True, condition_on_previous_text=False,
        initial_prompt="Jarvis, despierta. Jarvis, duérmete. Jarvis, abre YouTube.")
    texto = " ".join(s.text.strip() for s in segmentos).strip()
    basura = ["amara.org", "subtitulos", "suscribete", "gracias por ver"]
    if len(texto) < 2 or any(b in sin_acentos(texto.lower()) for b in basura):
        return ""
    return texto


def escuchar(espera_max=None):
    poner_estado("escuchando" if estado["despierto"] else "dormido")
    if not MODO_VOZ:
        try:
            texto = input("Tú: ").strip()
        except EOFError:
            return None
        if texto:
            estado["sub_tu"] = texto
        return texto or None
    audio = grabar_frase(espera_max)
    if audio is None:
        return None
    poner_estado("pensando")
    t0 = time.time()
    texto = transcribir(audio)
    if MOSTRAR_TIEMPOS:
        print(f"   (oído: {time.time() - t0:.1f} s)")
    if texto:
        print("Tú:", texto)
        estado["sub_tu"] = texto
    elif MOSTRAR_TIEMPOS:
        print("   (he captado sonido pero no he entendido nada)")
    return texto or None


def confirmar(pregunta):
    hablar(pregunta)
    r = escuchar(espera_max=8)
    if not r:
        return False
    palabras = normalizar(r).split()
    return any(p in palabras for p in
               ["si", "vale", "claro", "confirmo", "adelante", "dale", "guardalo", "s"])


# =====================================================================
#  MEMORIA
# =====================================================================
def cargar_memoria():
    if os.path.exists(ARCHIVO_MEMORIA):
        try:
            with open(ARCHIVO_MEMORIA, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def guardar_memoria(datos):
    with open(ARCHIVO_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def personalidad_con_memoria(datos):
    if not datos:
        return PERSONALIDAD
    lista = "\n".join("- " + d for d in datos)
    return (PERSONALIDAD
            + "\n\nCosas que sabes del usuario (úsalas solo cuando vengan a cuento, "
            + "sin soltarlas todas de golpe):\n" + lista)


memoria = cargar_memoria()
historial = [{"role": "system", "content": personalidad_con_memoria(memoria)}]
historial_desahogo = [{"role": "system", "content": PERSONALIDAD_DESAHOGO}]


# =====================================================================
#  CEREBRO (Ollama)
# =====================================================================
def preguntar_crudo(mensajes):
    r = ollama.chat(model=MODELO, messages=mensajes, think=False, keep_alive="1h")
    return r["message"]["content"].strip()


def preguntar(mensajes):
    return limpiar_para_voz(preguntar_crudo(mensajes))


def calentar_modelo():
    """Carga el modelo en la gráfica al arrancar para que la primera respuesta no tarde."""
    try:
        ollama.chat(model=MODELO, messages=[{"role": "user", "content": "hola"}],
                    think=False, keep_alive="1h", options={"num_predict": 1})
    except Exception:
        pass


def recortar(hist, maximo=16):
    return [hist[0]] + hist[1:][-maximo:]


def hablar_stream(mensajes):
    """Pide la respuesta al modelo y la va diciendo frase a frase.
    Devuelve el texto completo o None si algo falla."""
    poner_estado("pensando")
    buffer = ""
    completo = []
    try:
        for trozo in ollama.chat(model=MODELO, messages=mensajes, think=False,
                                 stream=True, keep_alive="1h"):
            buffer += trozo["message"]["content"]
            while True:
                corte = None
                for m in re.finditer(r"[.!?…]+\s", buffer):
                    if m.end() >= 25:
                        corte = m.end()
                        break
                if corte is None:
                    break
                frase = limpiar_para_voz(buffer[:corte])
                buffer = buffer[corte:]
                if frase:
                    completo.append(frase)
                    estado["sub_jarvis"] = " ".join(completo)
                    encolar_voz(frase)
        resto = limpiar_para_voz(buffer)
        if resto:
            completo.append(resto)
            estado["sub_jarvis"] = " ".join(completo)
            encolar_voz(resto)
    except Exception as e:
        esperar_voz()
        print("(Error con el modelo:", e, ")")
        if not completo:
            hablar("Se me ha cruzado un cable, illo. ¿Está Ollama abierto?")
            return None
    esperar_voz()
    respuesta = " ".join(completo)
    if not respuesta:
        hablar("Me he quedado en blanco, pisha. Repítemelo.")
        return None
    estado["ultima"] = respuesta
    print("Jarvis:", respuesta)
    return respuesta


def charlar(texto, hist, indicacion=""):
    """Charla normal con memoria de la conversación."""
    contenido = texto + (f"\n({indicacion})" if indicacion else "")
    hist.append({"role": "user", "content": contenido})
    respuesta = hablar_stream(hist)
    if not respuesta:
        hist.pop()
        return
    hist[-1]["content"] = texto
    hist.append({"role": "assistant", "content": respuesta})
    hist[:] = recortar(hist)


def ia_una_vez(instruccion, indicacion=""):
    """Una petición suelta a la IA (chiste, cuento...) que no ensucia la charla."""
    mensajes = [
        {"role": "system", "content": PERSONALIDAD},
        {"role": "user", "content": instruccion + (f"\n({indicacion})" if indicacion else "")},
    ]
    return hablar_stream(mensajes)


def extraer_recuerdos(hist):
    conv = "\n".join(
        ("Usuario: " if m["role"] == "user" else "Jarvis: ") + m["content"]
        for m in hist if m["role"] != "system")
    if "Usuario:" not in conv:
        return []
    peticion = [{"role": "user", "content": (
        "Lee esta conversación y apunta SOLO datos personales duraderos que el "
        "usuario haya dicho de sí mismo (gustos, planes, personas, proyectos). "
        "No apuntes nada de salud, emociones ni intimidades, ni cosas pasajeras. "
        "Una línea por dato, empezando por '- ', con frases cortas. "
        "Si no hay nada que apuntar, responde solo: NADA.\n\n" + conv)}]
    texto = preguntar_crudo(peticion)
    return [l[2:].strip() for l in texto.splitlines() if l.startswith("- ")]


# =====================================================================
#  HERRAMIENTAS
# =====================================================================
# (los chistes salen ahora de las funciones del modo colega, sin repetirse)


UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho",
            "nueve", "diez", "once", "doce", "trece", "catorce", "quince",
            "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte",
            "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco",
            "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta"}
HORAS_PALABRAS = {1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis",
                  7: "siete", 8: "ocho", 9: "nueve", 10: "diez", 11: "once", 12: "doce"}


def numero_palabras(n):
    """De 0 a 59 en palabras."""
    if n < 30:
        return UNIDADES[n]
    d, u = divmod(n, 10)
    return DECENAS[d] if u == 0 else f"{DECENAS[d]} y {UNIDADES[u]}"


def periodo_dia(h):
    if h == 12:
        return "del mediodía"
    if h == 0 or h >= 21:
        return "de la noche"
    if h < 6:
        return "de la madrugada"
    if h < 12:
        return "de la mañana"
    return "de la tarde"


def hora_en_palabras(h, m, con_verbo=True):
    """20:00 -> 'Son las ocho de la tarde'; 21:45 -> 'Son las diez menos cuarto de la noche'."""
    if m >= 35:
        destino = (h + 1) % 24
        if m == 45:
            resto = "menos cuarto"
        elif m == 59:
            resto = "menos un minuto"
        else:
            resto = "menos " + numero_palabras(60 - m)
    elif m == 0:
        destino, resto = h, ""
    elif m == 15:
        destino, resto = h, "y cuarto"
    elif m == 30:
        destino, resto = h, "y media"
    elif m == 1:
        destino, resto = h, "y un minuto"
    else:
        destino, resto = h, "y " + numero_palabras(m)
    h12 = destino % 12 or 12
    if h12 == 1:
        sujeto, verbo = "la una", "Es"
    else:
        sujeto, verbo = f"las {HORAS_PALABRAS[h12]}", "Son"
    partes = [sujeto] + ([resto] if resto else []) + [periodo_dia(h)]
    frase = " ".join(partes)
    return f"{verbo} {frase}" if con_verbo else frase


def decir_hora():
    ahora = datetime.datetime.now()
    hablar(hora_en_palabras(ahora.hour, ahora.minute) + ".")


def decir_fecha():
    h = datetime.date.today()
    hablar(f"Hoy es {DIAS[h.weekday()]} {h.day} de {MESES[h.month - 1]}.")


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisCasero/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def descripcion_tiempo(codigo):
    if codigo == 0:
        return "cielo despejado"
    if codigo in (1, 2, 3):
        return "algo de nubes"
    if codigo in (45, 48):
        return "niebla"
    if 51 <= codigo <= 57:
        return "llovizna"
    if 61 <= codigo <= 67:
        return "lluvia"
    if 71 <= codigo <= 77:
        return "nieve"
    if 80 <= codigo <= 82:
        return "chubascos"
    if codigo >= 95:
        return "tormenta"
    return "tiempo variable"


def decir_tiempo(ciudad):
    poner_estado("pensando")
    try:
        g = http_json("https://geocoding-api.open-meteo.com/v1/search?" +
                      urllib.parse.urlencode({"name": ciudad, "count": 1,
                                              "language": "es", "format": "json"}))
        if not g.get("results"):
            hablar(f"No encuentro {ciudad}, pisha.")
            return
        lugar = g["results"][0]
        d = http_json("https://api.open-meteo.com/v1/forecast?" +
                      urllib.parse.urlencode({
                          "latitude": lugar["latitude"],
                          "longitude": lugar["longitude"],
                          "current": "temperature_2m,weather_code,wind_speed_10m",
                          "timezone": "auto"}))
        c = d["current"]
        hablar(f"En {lugar['name']} hay {descripcion_tiempo(c['weather_code'])}, "
               f"{round(c['temperature_2m'])} grados y viento de "
               f"{round(c['wind_speed_10m'])} kilómetros por hora.")
    except Exception:
        hablar("No he podido mirar el tiempo ahora mismo. ¿Tienes internet?")


OPERACIONES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
               ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}


def evaluar_seguro(expr):
    """Calcula una operación sin usar eval (solo números y operadores)."""
    def ev(nodo):
        if isinstance(nodo, ast.Expression):
            return ev(nodo.body)
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
            return nodo.value
        if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, (ast.UAdd, ast.USub)):
            v = ev(nodo.operand)
            return v if isinstance(nodo.op, ast.UAdd) else -v
        if isinstance(nodo, ast.BinOp) and type(nodo.op) in OPERACIONES:
            a, b = ev(nodo.left), ev(nodo.right)
            if isinstance(nodo.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e6):
                raise ValueError("demasiado grande")
            return OPERACIONES[type(nodo.op)](a, b)
        raise ValueError("no permitido")
    return ev(ast.parse(expr, mode="eval"))


def formatear_numero(x):
    if x < 0:
        return "menos " + formatear_numero(-x)
    if isinstance(x, float):
        if x.is_integer() and abs(x) < 1e15:
            return str(int(x))
        return format(round(x, 6), "f").rstrip("0").rstrip(".").replace(".", ",")
    return str(x)


NUM_UNI = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
           "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
           "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
           "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
           "veinte": 20, "veintiun": 21, "veintiuno": 21, "veintiuna": 21,
           "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
           "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
NUM_DEC = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
           "setenta": 70, "ochenta": 80, "noventa": 90}
NUM_CEN = {"cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
           "trescientos": 300, "trescientas": 300, "cuatrocientos": 400,
           "cuatrocientas": 400, "quinientos": 500, "quinientas": 500,
           "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
           "setecientas": 700, "ochocientos": 800, "ochocientas": 800,
           "novecientos": 900, "novecientas": 900}
SIGNOS = ".,;:!?¡¿()"


def palabras_a_numeros(t):
    """'cuatro por treinta y siete' -> '4 por 37'. Las cifras se dejan como están."""
    tokens = t.replace("por ciento", "porciento").split()   # que "por ciento" no cuente como 100
    salida = []
    i = 0
    while i < len(tokens):
        w = tokens[i].strip(SIGNOS)
        siguiente = tokens[i + 1].strip(SIGNOS) if i + 1 < len(tokens) else ""
        if w in ("un", "una") and siguiente not in ("mil", "millon", "millones"):
            salida.append(tokens[i])      # es el artículo ("un cuento"), no el número 1
            i += 1
            continue
        if w in NUM_UNI or w in NUM_DEC or w in NUM_CEN or w in ("mil", "millon", "millones"):
            total, actual, tipo = 0, 0, ""
            while i < len(tokens):
                w = tokens[i].strip(SIGNOS)
                if w in NUM_UNI and tipo != "uni":
                    actual += NUM_UNI[w]
                    tipo = "uni"
                elif w in NUM_DEC and tipo not in ("uni", "dec"):
                    actual += NUM_DEC[w]
                    tipo = "dec"
                elif w in NUM_CEN and tipo not in ("uni", "dec", "cen"):
                    actual += NUM_CEN[w]
                    tipo = "cen"
                elif (w == "y" and tipo == "dec" and i + 1 < len(tokens)
                      and 1 <= NUM_UNI.get(tokens[i + 1].strip(SIGNOS), 0) <= 9):
                    tipo = "y"
                elif w == "mil" and tipo in ("", "uni", "dec", "cen"):
                    total += (actual or 1) * 1000
                    actual, tipo = 0, "mil"
                elif w in ("millon", "millones") and tipo in ("", "uni", "dec", "cen"):
                    total += (actual or 1) * 1000000
                    actual, tipo = 0, "millon"
                else:
                    break
                i += 1
            salida.append(str(total + actual))
        else:
            salida.append(tokens[i])
            i += 1
    return " ".join(salida).replace("porciento", "por ciento")


FILLER_CALCULO = (r"(?:(?:cuanto es|cuanto son|cuantos son|cuanto da|cuanto suma|calcula|"
                  r"calculame|dime|haz|hazme|a ver|venga|vamos|pues|y|el resultado de|"
                  r"resultado de)\s+)*")


def parece_calculo(texto):
    """True si lo que has dicho parece una cuenta: '4 por 9', 'cuatro por nueve', 'cuánto es 25 más 3'..."""
    t = palabras_a_numeros(sin_acentos(texto.lower()).strip(" .,;:!?¡¿"))
    t = re.sub(r"(\d+)\s+coma\s+(\d+)", r"\1.\2", t)
    t = re.sub(r",\s+", " ", t)
    if re.match(r"^(cuanto|cuantos|calcula|calculame|dime cuanto|dime cuantos|"
                r"cual es la raiz|raiz|resultado de)\b", t):
        return True
    if re.search(r"\d\s*(?:%|por ciento)\s*de\s*\d", t):
        return True
    return bool(re.match(
        r"^" + FILLER_CALCULO + r"[\d(][\d.,()]*\s*(?:mas\b|menos\b|por\b|entre\b|dividido|"
        r"elevado|al cuadrado|al cubo|%|x|×|\*|\+|-|/)", t))


def calcular(texto):
    """Devuelve el resultado en texto, 'CERO' si dividen entre cero o None si no es una cuenta."""
    t = palabras_a_numeros(sin_acentos(texto.lower()))
    t = re.sub(r"(\d+)\s+coma\s+(\d+)", r"\1.\2", t)           # dos coma cinco -> 2.5
    t = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", t)      # 1.000 -> 1000
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)                # 2,5 -> 2.5
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|por ciento)\s*de\s*(\d+(?:\.\d+)?)", t)
    if m:
        return formatear_numero(float(m.group(1)) / 100 * float(m.group(2)))
    m = re.search(r"raiz (cuadrada|cubica) de (\d+(?:\.\d+)?)", t)
    if m:
        x = float(m.group(2))
        return formatear_numero(math.sqrt(x) if m.group(1) == "cuadrada"
                                else round(x ** (1 / 3), 10))
    t = t.replace("×", "*").replace("÷", "/")
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", t)                  # 4x9 -> 4*9
    t = re.sub(r"\b(multiplicado por|multiplicado|por|x)\b", "*", t)
    t = re.sub(r"\b(dividido entre|dividido por|dividido|entre)\b", "/", t)
    t = re.sub(r"\b(elevado a la|elevado a|a la potencia de)\b", "**", t)
    t = re.sub(r"\bal cuadrado\b", "**2", t)
    t = re.sub(r"\bal cubo\b", "**3", t)
    t = re.sub(r"\bmas\b", "+", t)
    t = re.sub(r"\bmenos\b", "-", t)
    trozos = [x.strip() for x in re.findall(r"[\d.()+\-*/ ]{3,}", t)
              if re.search(r"\d", x) and re.search(r"[+\-*/]", x)]
    if not trozos:
        return None
    try:
        return formatear_numero(evaluar_seguro(max(trozos, key=len)))
    except ZeroDivisionError:
        return "CERO"
    except (ValueError, OverflowError) as e:
        return "GRANDE" if isinstance(e, OverflowError) or "grande" in str(e) else None
    except Exception:
        return None


def hacer_calculo(texto):
    """True si era una cuenta y ya la ha respondido."""
    res = calcular(texto)
    if res is None:
        return False
    if res == "CERO":
        hablar("Entre cero no se puede dividir, illo, que se rompe el universo.")
    elif res == "GRANDE":
        hablar("Eso es un número gigante, pisha, no me cabe en la cabeza.")
    else:
        hablar(random.choice([f"Son {res}.", f"Da {res}.", f"El resultado es {res}, pisha."]))
    return True


def azar(n):
    """Dados, monedas y números al azar. True si lo ha gestionado."""
    if re.search(r"\bdado\b", n) and re.search(r"\b(tira|tirame|lanza|lanzame|echa|echame|saca)\b", n):
        m = re.search(r"\bde (\d+)\b", n)
        caras = int(m.group(1)) if m and 2 <= int(m.group(1)) <= 1000 else 6
        hablar(f"Ha salido el {random.randint(1, caras)}.")
        return True
    if re.search(r"\bcara o cruz\b", n) or (
            re.search(r"\bmoneda\b", n) and re.search(r"\b(tira|echa|lanza)\w*", n)):
        hablar(random.choice(["Ha salido cara.", "Ha salido cruz."]))
        return True
    m = re.search(r"\bnumero\b.*\bentre (\d+) y (\d+)", n)
    if m:
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        hablar(f"Te sale el {random.randint(a, b)}.")
        return True
    return False


CONVERSIONES = {
    # alias: (tipo, nombre, factor a la unidad base)
    "kilometro": ("longitud", "kilómetros", 1000.0), "kilometros": ("longitud", "kilómetros", 1000.0),
    "km": ("longitud", "kilómetros", 1000.0),
    "metro": ("longitud", "metros", 1.0), "metros": ("longitud", "metros", 1.0),
    "centimetro": ("longitud", "centímetros", 0.01), "centimetros": ("longitud", "centímetros", 0.01),
    "cm": ("longitud", "centímetros", 0.01),
    "milla": ("longitud", "millas", 1609.344), "millas": ("longitud", "millas", 1609.344),
    "pie": ("longitud", "pies", 0.3048), "pies": ("longitud", "pies", 0.3048),
    "pulgada": ("longitud", "pulgadas", 0.0254), "pulgadas": ("longitud", "pulgadas", 0.0254),
    "kilo": ("masa", "kilos", 1.0), "kilos": ("masa", "kilos", 1.0),
    "kilogramo": ("masa", "kilos", 1.0), "kilogramos": ("masa", "kilos", 1.0), "kg": ("masa", "kilos", 1.0),
    "gramo": ("masa", "gramos", 0.001), "gramos": ("masa", "gramos", 0.001),
    "libra": ("masa", "libras", 0.45359237), "libras": ("masa", "libras", 0.45359237),
    "onza": ("masa", "onzas", 0.028349523125), "onzas": ("masa", "onzas", 0.028349523125),
    "litro": ("volumen", "litros", 1.0), "litros": ("volumen", "litros", 1.0),
    "mililitro": ("volumen", "mililitros", 0.001), "mililitros": ("volumen", "mililitros", 0.001),
    "galon": ("volumen", "galones", 3.785411784), "galones": ("volumen", "galones", 3.785411784),
}
TEMPERATURAS = {"celsius": "grados Celsius", "centigrados": "grados Celsius",
                "fahrenheit": "grados Fahrenheit"}
NUM = r"(\d+(?:\.\d+)?)"


def texto_math(texto):
    """Pasa a minúsculas, sin acentos y con los números en cifras."""
    t = palabras_a_numeros(sin_acentos(texto.lower()).strip(" .,;:!?¡¿"))
    t = re.sub(r"(\d+)\s+coma\s+(\d+)", r"\1.\2", t)
    t = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", t)
    return re.sub(r"(?<=\d),(?=\d)", ".", t)


def convertir_temperatura(t):
    m = re.search(NUM + r"\s*(?:grados\s+)?(celsius|centigrados|fahrenheit)\s+(?:a|en)\s+"
                  r"(?:grados\s+)?(celsius|centigrados|fahrenheit)", t)
    if not m:
        m2 = re.search(r"cuantos grados (celsius|centigrados|fahrenheit) (?:son|es|hay en) "
                       + NUM + r"\s*(?:grados\s+)?(celsius|centigrados|fahrenheit)", t)
        if not m2:
            return None
        destino, valor, origen = m2.group(1), float(m2.group(2)), m2.group(3)
    else:
        valor, origen, destino = float(m.group(1)), m.group(2), m.group(3)
    o_c = origen != "fahrenheit"
    d_c = destino != "fahrenheit"
    if o_c == d_c:
        res = valor
    elif o_c:
        res = valor * 9 / 5 + 32
    else:
        res = (valor - 32) * 5 / 9
    return (f"{formatear_numero(valor)} {TEMPERATURAS[origen]} son "
            f"{formatear_numero(round(res, 1))} {TEMPERATURAS[destino]}.")


def convertir_unidades(t):
    """'convierte 10 kilómetros a millas', 'cuántas millas son 5 kilómetros'..."""
    r = convertir_temperatura(t)
    if r:
        return r
    m = re.search(r"(?:convierte|convertir|pasa|pasame|cambia)\s+" + NUM + r"\s+([a-z]+)\s+(?:a|en)\s+([a-z]+)", t)
    if m:
        valor, o, d = float(m.group(1)), m.group(2), m.group(3)
    else:
        m = re.search(r"cuantos?\s+([a-z]+)\s+(?:son|es|hay en|hay)\s+" + NUM + r"\s+([a-z]+)", t) \
            or re.search(r"cuantas?\s+([a-z]+)\s+(?:son|es|hay en|hay)\s+" + NUM + r"\s+([a-z]+)", t)
        if m:
            d, valor, o = m.group(1), float(m.group(2)), m.group(3)
        else:
            m = re.match(r"^" + NUM + r"\s+([a-z]+)\s+(?:a|en)\s+([a-z]+)$", t)
            if not m:
                return None
            valor, o, d = float(m.group(1)), m.group(2), m.group(3)
    if o not in CONVERSIONES or d not in CONVERSIONES:
        return None
    tipo_o, nombre_o, f_o = CONVERSIONES[o]
    tipo_d, nombre_d, f_d = CONVERSIONES[d]
    if tipo_o != tipo_d:
        return f"No puedo pasar {nombre_o} a {nombre_d}, illo, son cosas distintas."
    res = valor * f_o / f_d
    return f"{formatear_numero(valor)} {nombre_o} son {formatear_numero(round(res, 2))} {nombre_d}."


def es_primo(k):
    if k < 2:
        return False
    i = 2
    while i * i <= k:
        if k % i == 0:
            return False
        i += 1
    return True


def matematicas_extra(texto):
    """Factoriales, primos, tablas, porcentajes, medias, conversiones... True si lo ha resuelto."""
    t = texto_math(texto)

    m = re.search(r"\bfactorial de (\d+)\b", t)
    if m:
        k = int(m.group(1))
        if k > 20:
            hablar("Ese factorial es gigantesco, illo, no me cabe en la cabeza.")
        else:
            hablar(f"El factorial de {k} es {math.factorial(k)}.")
        return True

    m = re.search(r"\bes primo (?:el |al )?(\d+)\b", t) or re.search(r"\b(\d+) es (?:un numero )?primo\b", t)
    if m:
        k = int(m.group(1))
        if k > 10 ** 12:
            hablar("Ese número es demasiado grande para mí, pisha.")
        elif es_primo(k):
            hablar(f"Sí, el {k} es primo.")
        else:
            hablar(f"No, el {k} no es primo.")
        return True

    m = re.search(r"\btabla (?:de multiplicar )?(?:del?|de los) (\d+)\b", t)
    if m:
        k = int(m.group(1))
        hablar(f"Tabla del {k}. " + " ".join(f"{k} por {i}, {k * i}." for i in range(1, 11)))
        return True

    m = re.search(r"\bque porcentaje (?:es|supone|representa) " + NUM + r" de " + NUM, t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        if b == 0:
            hablar("Entre cero no se puede, illo.")
        else:
            hablar(f"Es el {formatear_numero(round(a / b * 100, 2))} por ciento.")
        return True

    m = re.search(r"\b(?:descuento|rebaja)\s+(?:del?\s+)?" + NUM + r"\s*(?:%|por ciento)\s+(?:a|en|sobre|de)\s+" + NUM, t)
    if m:
        p, base = float(m.group(1)), float(m.group(2))
        final = base * (1 - p / 100)
        hablar(f"Con un {formatear_numero(p)} por ciento de descuento se queda en "
               f"{formatear_numero(round(final, 2))}. Te ahorras {formatear_numero(round(base - final, 2))}.")
        return True

    m = re.search(r"\b(?:aumenta|aumentale|sube|subele|incrementa|incrementale)\s+" + NUM
                  + r"\s+(?:un\s+|el\s+)?" + NUM + r"\s*(?:%|por ciento)", t)
    if m:
        base, p = float(m.group(1)), float(m.group(2))
        hablar(f"Sube a {formatear_numero(round(base * (1 + p / 100), 2))}.")
        return True

    if re.search(r"\b(?:media|promedio)\s+de\b", t):
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
        if len(nums) >= 2:
            hablar(f"La media es {formatear_numero(round(sum(nums) / len(nums), 4))}.")
            return True

    m = re.search(r"\bmaximo comun divisor de " + r"(\d+) y (\d+)", t) or re.search(r"\bmcd de (\d+) y (\d+)", t)
    if m:
        hablar(f"El máximo común divisor es {math.gcd(int(m.group(1)), int(m.group(2)))}.")
        return True
    m = re.search(r"\bminimo comun multiplo de (\d+) y (\d+)", t) or re.search(r"\bmcm de (\d+) y (\d+)", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        hablar(f"El mínimo común múltiplo es {a * b // math.gcd(a, b) if a and b else 0}.")
        return True

    m = re.search(r"\b(doble|triple|cuadruple|mitad|tercio|cuarto) de " + NUM, t)
    if m:
        factor = {"doble": 2, "triple": 3, "cuadruple": 4, "mitad": 0.5,
                  "tercio": 1 / 3, "cuarto": 0.25}[m.group(1)]
        hablar(f"Son {formatear_numero(round(float(m.group(2)) * factor, 4))}.")
        return True

    r = convertir_unidades(t)
    if r:
        hablar(r)
        return True
    return False


def tecla_volumen(sube, veces=5):
    vk = 0xAF if sube else 0xAE
    for _ in range(veces):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def abrir(peticion_n):
    arg = re.sub(r"^(abre|abreme|abrir|lanza|ejecuta)\s+", "", peticion_n)
    arg = re.sub(r"^(el|la|los|las|mi|un|una)\s+", "", arg).strip()
    for clave, destino in APPS.items():
        if clave in arg:
            try:
                if destino.startswith("http") or destino.endswith(":") or "://" in destino:
                    os.startfile(destino)
                else:
                    subprocess.Popen(["cmd", "/c", "start", "", destino])
                hablar(f"Hecho, abriendo {clave}.")
            except Exception:
                hablar(f"No he podido abrir {clave}, illo.")
            return
    if re.fullmatch(r"[a-z0-9\-]+(\.[a-z0-9\-]+)+", arg.replace(" ", "")):
        os.startfile("https://" + arg.replace(" ", ""))
        hablar(f"Abriendo {arg}.")
        return
    hablar(f"No sé abrir {arg}. Añádelo a la lista APPS del programa y lo abro.")


def buscar_web(consulta):
    resultados = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        for r in DDGS().text(consulta, region="es-es", max_results=5):
            resultados.append(f"{r.get('title', '')}: {r.get('body', '')}")
    except Exception:
        pass
    if not resultados:
        try:
            d = http_json("https://es.wikipedia.org/w/api.php?" +
                          urllib.parse.urlencode({"action": "query", "list": "search",
                                                  "srsearch": consulta, "format": "json",
                                                  "srlimit": 4}))
            for r in d["query"]["search"]:
                resultados.append(r["title"] + ": " +
                                  html.unescape(re.sub(r"<[^>]+>", "", r["snippet"])))
        except Exception:
            pass
    return resultados


def buscar_y_resumir(consulta, frases="dos o tres"):
    hablar("Dame un segundo, que lo busco.")
    poner_estado("pensando")
    res = buscar_web(consulta)
    if not res:
        hablar("No he podido buscar nada ahora mismo, illo. ¿Tienes internet?")
        return
    peticion = [
        {"role": "system", "content": PERSONALIDAD},
        {"role": "user", "content": (
            f"Pregunta del usuario: {consulta}\n\nResultados de internet:\n"
            + "\n".join(res)
            + f"\n\nResponde en {frases} frases cortas con lo que digan los "
              "resultados. Si no bastan para responder, dilo. No inventes nada.")}]
    try:
        hablar(preguntar(peticion))
    except Exception:
        hablar("Se me ha cruzado un cable resumiendo, illo.")


# ---------- recordatorios ----------
def parsear_recordatorio(t):
    t = t.lower()
    m = re.search(r"(?:recu[eé]rdame|av[ií]same)(?: que)? (.+?) (?:en|dentro de) "
                  r"(media|\d+|[a-záéíóú]+) (horas?|minutos?)\b", t)
    if m:
        txt, cant, unidad = m.group(1), m.group(2), m.group(3)
        if cant == "media":
            minutos = 30
        else:
            valor = int(cant) if cant.isdigit() else NUMEROS.get(sin_acentos(cant))
            if valor is None:
                return None
            minutos = valor * 60 if unidad.startswith("hora") else valor
        return datetime.datetime.now() + datetime.timedelta(minutes=minutos), txt.strip()
    m = re.search(r"(?:recu[eé]rdame|av[ií]same)(?: que)? (.+?) a las (\d{1,2})(?:[: ](\d{2}))?", t)
    if m:
        txt, hh, mm = m.group(1), int(m.group(2)), int(m.group(3) or 0)
        if hh > 23 or mm > 59:
            return None
        ahora = datetime.datetime.now()
        cuando = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cuando <= ahora:
            cuando += datetime.timedelta(days=1)
        return cuando, txt.strip()
    return None


def poner_recordatorio(texto):
    r = parsear_recordatorio(texto)
    if not r:
        hablar("No he pillado cuándo. Dime algo como: recuérdame sacar la basura en diez minutos.")
        return
    cuando, txt = r
    recordatorios.append({"cuando": cuando, "texto": txt})
    hablar(f"Hecho, te lo recuerdo a {hora_en_palabras(cuando.hour, cuando.minute, False)}.")


def poner_temporizador(texto):
    t = texto.lower()
    m = re.search(r"temporizador (?:de |para )?(media|\d+|[a-záéíóú]+)(?: y (?:medio|media))? "
                  r"(segundos?|minutos?|horas?)", t)
    if not m:
        hablar("Dime cuánto, por ejemplo: pon un temporizador de cinco minutos.")
        return
    cant, unidad = m.group(1), m.group(2)
    if cant == "media":
        segundos = 1800 if unidad.startswith("hora") else 30
    else:
        valor = int(cant) if cant.isdigit() else NUMEROS.get(sin_acentos(cant))
        if valor is None:
            hablar("No he pillado el número, illo. Prueba con una cifra, como cinco minutos.")
            return
        mult = 3600 if unidad.startswith("hora") else 60 if unidad.startswith("minuto") else 1
        segundos = valor * mult
    recordatorios.append({
        "cuando": datetime.datetime.now() + datetime.timedelta(seconds=segundos),
        "texto": "temporizador",
        "mensaje": "¡Se acabó el temporizador, illo!"})
    hablar(f"Temporizador puesto: {cant} {unidad}.")


def recordatorio_vencido():
    ahora = datetime.datetime.now()
    return any(r["cuando"] <= ahora for r in recordatorios)


def entregar_recordatorios():
    ahora = datetime.datetime.now()
    for r in [r for r in recordatorios if r["cuando"] <= ahora]:
        recordatorios.remove(r)
        mensaje = r.get("mensaje") or f"Oye, que tenías esto pendiente: {r['texto']}."
        if estado["no_molestar"]:
            print("(Recordatorio en silencio):", mensaje)
        else:
            hablar(mensaje)


# ---------- modo colega ----------
def animar():
    hablar(sacar("animo", ANIMOS))


def jugar(pregunta, validas):
    hablar(pregunta)
    r = escuchar(espera_max=15)
    if not r:
        return "tiempo"
    n = normalizar(r)
    return "acierto" if any(v in n.split() or v in n for v in validas) else "fallo"


def resultado_juego(res, respuesta, cierre):
    if res == "acierto":
        hablar(f"¡Correcto, illo! Eres un máquina. {cierre}")
    elif res == "fallo":
        hablar(f"Casi, pisha. Era: {respuesta}. {cierre}")
    else:
        hablar(f"Se acabó el tiempo. Era: {respuesta}. {cierre}")


def trivia():
    marcar("reto")
    pregunta, validas, respuesta = sacar_juego("trivia", TRIVIA)
    resultado_juego(jugar(pregunta, validas), respuesta, "Si quieres otro reto, dímelo.")


def adivinanza():
    marcar("adivinanza")
    pregunta, validas, respuesta = sacar_juego("adivinanza", ADIVINANZAS)
    resultado_juego(jugar(pregunta, validas), respuesta, "Si quieres otra adivinanza, dímelo.")


pendientes = {}


def sacar(clave, lista):
    """Elige sin repetir hasta que se han dicho todos."""
    if not pendientes.get(clave):
        pendientes[clave] = random.sample(lista, len(lista))
    return pendientes[clave].pop()


def sacar_juego(clave, lista):
    return sacar(clave, lista)


def marcar(tipo, tema=None):
    """Apunta lo último que has pedido para poder responder a 'otro'."""
    estado["ultimo_tipo"] = tipo
    estado["ultimo_tema"] = tema
    estado["ultimo_t"] = time.time()


def categoria(n, mapa):
    """Busca en lo que has dicho un tema conocido (informática, animales, espacio...)."""
    palabras = set(n.split())
    for cat, claves in mapa.items():
        if palabras & set(claves):
            return cat
    return None


def pide_otro(n, tipo):
    return (re.match(r"^(otro|otra|dame otro|dame otra|venga otro|venga otra)\b", n)
            and estado["ultimo_tipo"] == tipo and time.time() - estado["ultimo_t"] < 180)


def chiste_de(cat):
    marcar("chiste", cat)
    hablar(sacar("chiste_" + str(cat), CHISTES[cat] if cat else TODOS_CHISTES))


def contar_chiste(n):
    cat = categoria(n, TEMAS_CHISTES)
    if cat is None and pide_otro(n, "chiste"):
        cat = estado["ultimo_tema"]
    elif cat is None and re.search(r"\bchistes? (?:de|sobre|acerca de) \w", n):
        hablar("De eso no tengo chistes, pero toma uno de los míos.")
    chiste_de(cat)


def dato_de(cat):
    marcar("dato", cat)
    hablar(sacar("dato_" + str(cat), DATOS[cat] if cat else TODOS_DATOS))


def contar_dato(n):
    cat = categoria(n, TEMAS_DATOS)
    if cat is None and pide_otro(n, "dato"):
        cat = estado["ultimo_tema"]
    elif cat is None and re.search(r"\b(?:de|sobre|acerca de) \w", n):
        hablar("De eso no tengo curiosidades, pero esta te va a gustar.")
    dato_de(cat)


def vacilar():
    marcar("vacile")
    hablar(sacar("vacile", VACILES))


def piropo():
    marcar("piropo")
    hablar(sacar("piropo", PIROPOS))


def excusa():
    marcar("excusa")
    hablar(sacar("excusa", EXCUSAS))


def refran():
    marcar("refran")
    hablar(sacar("refran", REFRANES))


def trabalenguas():
    marcar("trabalenguas")
    hablar(sacar("trabalenguas", TRABALENGUAS) + " A ver si tú puedes repetirlo.")


def cuento_de(cat):
    marcar("cuento", cat)
    hablar(sacar("cuento_" + str(cat), CUENTOS[cat] if cat else TODOS_CUENTOS))


def cuento(n):
    cuento_de(categoria(n, TEMAS_CUENTOS))


def repetir_ultimo():
    """Responde a 'otro' / 'otra' repitiendo lo último que has pedido."""
    tipo, tema = estado["ultimo_tipo"], estado["ultimo_tema"]
    acciones = {
        "chiste": lambda: chiste_de(tema), "dato": lambda: dato_de(tema),
        "vacile": vacilar, "piropo": piropo, "excusa": excusa, "refran": refran,
        "cuento": lambda: cuento_de(tema), "adivinanza": adivinanza,
        "trabalenguas": trabalenguas, "reto": trivia,
    }
    if tipo in acciones:
        acciones[tipo]()
        return True
    return False


def diario():
    hablar("Cuéntame qué tal el día, que lo apunto.")
    r = escuchar(espera_max=20)
    if not r:
        hablar("No he oído nada, lo dejamos para luego.")
        return
    with open(ARCHIVO_DIARIO, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}] {r}\n")
    hablar("Apuntado en tu diario.")


AYUDA = [
    "Control: despierta, duérmete, no molestar, silencio, apágate del todo, repite eso, más despacio o más rápido, volumen arriba o abajo.",
    "Utilidades: la hora, el tiempo, recordatorios, temporizadores, abrir programas y webs, buscar en internet, noticias, bloquear o apagar el ordenador.",
    "Cuentas: 4 por 9, cuánto es 25 más 3, el 15 por ciento de 200, raíz cuadrada de 81, factorial de 5, es primo el 17, tabla del 7, descuento del 20 por ciento a 50, media de 4 8 y 10, convierte 10 kilómetros a millas, tira un dado, cara o cruz.",
    "Humor y curiosidades (sin IA, al instante): chistes (también 'chiste de informáticos', de animales, de comida, de deporte...), datos curiosos (del espacio, animales, cuerpo, historia...), vacílame, piropo, excusa, refrán, cuento, adivinanza, trabalenguas, anímame, y di 'otro' para repetir.",
    "IA: pregúntame lo que quieras, traduce, explícame, define, dame ideas, redacta...",
    "Memoria: recuerda que..., qué recuerdas, olvida todo.",
]

# =====================================================================
#  CIERRE
# =====================================================================
def cerrar_del_todo():
    try:
        nuevos = extraer_recuerdos(historial)
    except Exception:
        nuevos = []
    if nuevos:
        print("Jarvis: Me quedaría con esto de lo que hemos hablado:")
        for n in nuevos:
            print("   -", n)
        if confirmar("¿Lo guardo?"):
            memoria.extend(nuevos)
            guardar_memoria(memoria)
            hablar("Apuntado.")
    hablar("Venga, hasta luego, illo.")
    return False


# =====================================================================
#  CEREBRO DE COMANDOS
# =====================================================================
def tema_de(texto):
    """Saca el tema de frases como 'un chiste de informáticos' (conservando los acentos)."""
    m = re.search(r"\b(?:de|sobre|acerca de) (.+)$", texto.lower().strip(" .,!?¡¿"))
    return m.group(1) if m else None


def procesar(texto):
    """Devuelve False cuando hay que cerrar el programa."""
    n = normalizar(texto)
    nombre = menciona_nombre(n)

    # Dormido: solo escucha "Jarvis, despierta"
    if not estado["despierto"]:
        if nombre and ("despiert" in n or "arriba" in n):
            estado["despierto"] = True
            hablar(random.choice(SALUDOS))
        return True

    # No molestar: solo responde si le llamas por su nombre
    if estado["no_molestar"] and not nombre:
        return True

    texto = quitar_nombre(texto)
    n = normalizar(texto)
    if not n:
        hablar("Dime, illo.")
        return True

    # ---------- control ----------
    if "apagate del todo" in n or "cierrate del todo" in n or n == "cierrate":
        return cerrar_del_todo()

    if "duermete" in n or "a dormir" in n:
        estado["despierto"] = False
        estado["desahogo"] = False
        hablar(random.choice(DESPEDIDAS_SUENO))
        return True

    # ---------- modo desahogo ----------
    if estado["desahogo"]:
        if any(f in n for f in ["ya estoy mejor", "salir del modo desahogo",
                                "cambiemos de tema", "termina el modo desahogo"]):
            estado["desahogo"] = False
            historial_desahogo[:] = historial_desahogo[:1]
            hablar("Vale, aquí me tienes para lo que haga falta. ¿Cambiamos de tema?")
        else:
            charlar(texto, historial_desahogo)
        return True

    if "no molestar" in n or "no me molestes" in n:
        if any(p in n for p in ["quita", "desactiva", "fuera", "sal de", "ya puedes"]):
            estado["no_molestar"] = False
            hablar("Vale, vuelvo a la normalidad.")
        else:
            hablar("Hecho. No te molesto hasta que me llames por mi nombre.")
            estado["no_molestar"] = True
        return True

    if any(p in n for p in ["mas despacio", "mas lento", "mas rapido", "mas deprisa"]):
        paso = -15 if ("despacio" in n or "lento" in n) else 15
        estado["velocidad"] = max(-40, min(40, estado["velocidad"] + paso))
        hablar("Vale, a ver qué tal así.")
        return True

    if estado["callado"] and ("ya puedes hablar" in n or "vuelve a hablar" in n or n == "habla"):
        estado["callado"] = False
        hablar("Aquí estoy otra vez.")
        return True

    if n in ("silencio", "callate", "cayate") or "callate un rato" in n:
        print("Jarvis: Vale, me callo. (Di 'habla' para que vuelva a hablar)")
        estado["callado"] = True
        return True

    if "repite" in n or "repitelo" in n:
        hablar(estado["ultima"] or "No he dicho nada todavía, illo.")
        return True

    if "que puedes hacer" in n or "comandos" in n or n == "ayuda":
        for linea in AYUDA:
            print("  -", linea)
        hablar("Puedo decirte la hora y el tiempo, ponerte recordatorios y temporizadores, "
               "abrir programas y webs, buscar en internet y contarte las noticias, hacer "
               "cuentas, tirar un dado, contarte chistes y curiosidades, adivinanzas y cuentos, animarte, "
               "escucharte si quieres desahogarte, hacerte retos y llevar tu diario. "
               "Y puedes preguntarme lo que quieras, que para eso soy una IA. Recuerdo lo "
               "que me cuentes.")
        return True

    if "volumen" in n:
        if any(p in n for p in ["sub", "arriba", "mas", "alto"]):
            tecla_volumen(True)
            hablar("Subido.")
        elif any(p in n for p in ["baj", "abajo", "menos", "bajo"]):
            tecla_volumen(False)
            hablar("Bajado.")
        return True

    # ---------- utilidades ----------
    if re.search(r"\bque hora\b|\bhora es\b|\bla hora\b", n):
        decir_hora()
        return True

    if re.search(r"\bque dia es\b|\bfecha\b|\ba cuantos estamos\b", n):
        decir_fecha()
        return True

    if re.search(r"\bque tiempo\b|\bclima\b|\bva a llover\b|\btemperatura\b", n):
        m = re.search(r"\ben ([a-z ]+)$", n)
        ciudad = m.group(1).strip() if m else CIUDAD
        if ciudad in ("hoy", "casa", "ahora", "la calle"):
            ciudad = CIUDAD
        decir_tiempo(ciudad)
        return True

    if re.search(r"\brecuerdame\b|\bavisame\b", n):
        poner_recordatorio(texto)
        return True

    if n.startswith("recuerda que"):
        dato = re.sub(r"^\s*recu[eé]rda que\s*", "", texto, flags=re.I).strip()
        if dato:
            memoria.append("El usuario me pidió recordar: " + dato)
            guardar_memoria(memoria)
            historial[0]["content"] = personalidad_con_memoria(memoria)
            hablar("Apuntado, illo.")
        return True

    if "que recuerdas" in n:
        if memoria:
            print("Jarvis: Esto es lo que tengo apuntado:")
            for m_ in memoria:
                print("   -", m_)
            hablar(f"Tengo {len(memoria)} cosas apuntadas. Te las he puesto en pantalla.")
        else:
            hablar("De momento no tengo nada apuntado, pisha.")
        return True

    if n == "olvida todo":
        if confirmar("¿Seguro que borro toda la memoria?"):
            memoria.clear()
            guardar_memoria(memoria)
            historial[0]["content"] = personalidad_con_memoria(memoria)
            hablar("Hecho, empezamos de cero.")
        return True

    if re.match(r"^(abre|abreme|abrir|lanza|ejecuta)\b", n):
        abrir(n)
        return True

    m = re.match(r"^(busca|buscame|buscar|investiga)\b(.*)$", n)
    if m:
        consulta = re.sub(r"^\s*(en internet|por internet|en google|sobre|acerca de|de)\s+",
                          "", m.group(2).strip())
        consulta = re.sub(r"^(en internet|por internet|en google|sobre|acerca de|de)\s+",
                          "", consulta).strip()
        if consulta:
            buscar_y_resumir(consulta)
        else:
            hablar("¿Qué quieres que busque, illo?")
        return True

    if re.search(r"\bbloquea\b|\bbloquear\b", n) and any(
            p in n for p in ["ordenador", "pantalla", "pc", "equipo", "sesion"]):
        hablar("Bloqueando el ordenador.")
        ctypes.windll.user32.LockWorkStation()
        return True

    if "cancela el apagado" in n:
        subprocess.run(["shutdown", "/a"])
        hablar("Apagado cancelado.")
        return True

    if re.search(r"\bapaga\b|\bapagar\b", n) and any(
            p in n for p in ["ordenador", "pc", "equipo"]):
        if confirmar("¿Seguro que apago el ordenador?"):
            subprocess.run(["shutdown", "/s", "/t", "30"])
            hablar("Apagando en treinta segundos. Di: cancela el apagado, si te arrepientes.")
        else:
            hablar("Vale, lo dejo encendido.")
        return True

    # ---------- cuentas, azar, temporizador, noticias ----------
    if matematicas_extra(texto):
        return True

    if parece_calculo(texto) and hacer_calculo(texto):
        return True

    if azar(n):
        return True

    if re.search(r"\btemporizador\b", n):
        poner_temporizador(texto)
        return True

    if re.search(r"\bnoticias\b|\bultima hora\b", n):
        consulta = texto if len(n.split()) > 4 else "últimas noticias de España hoy"
        buscar_y_resumir(consulta, "cuatro")
        return True

    if re.search(r"\b(quien gano|resultados? del|cotizacion|precio del|precio de la|"
                 r"precio de los|que ha pasado|que paso ayer)\b", n):
        buscar_y_resumir(texto)
        return True

    # ---------- modo colega (todo sin IA, al instante) ----------
    if re.match(r"^(otro|otra|uno mas|una mas|otro mas|otra mas|dame otro|dame otra|venga otro|venga otra)$", n):
        if time.time() - estado["ultimo_t"] < 180 and repetir_ultimo():
            return True

    if re.search(r"\bchistes?\b|\bhazme reir\b|\balgo gracioso\b|\bhazme una gracia\b", n):
        contar_chiste(n)
        return True

    if re.search(r"\bvacil\w*|\bburlate de mi\b|\bmeteme una puya\b|\bpicame\b", n):
        vacilar()
        return True

    if re.search(r"\bpiropos?\b", n):
        piropo()
        return True

    if re.search(r"\bexcusas?\b", n):
        excusa()
        return True

    if re.search(r"\brefran(?:es)?\b", n):
        refran()
        return True

    if re.search(r"\badivinanzas?\b", n):
        adivinanza()
        return True

    if re.search(r"\btrabalenguas?\b", n):
        trabalenguas()
        return True

    if (re.search(r"\bdatos? curiosos?\b|\bsorprendeme\b|\bdime algo interesante\b|"
                  r"\bcuentame algo interesante\b|\balgo curioso\b", n)
            or re.search(r"\b(dime|dame|cuentame|otra|una|alguna)\b.*\bcuriosidad(es)?\b", n)):
        contar_dato(n)
        return True

    if (re.search(r"\b(un cuento|una historia|un cuentito)\b", n)
            and re.search(r"\b(cuentame|cuenta|dime|inventa|echame|echa|quiero)\b", n)):
        cuento(n)
        return True

    if "animame" in n or "dame animos" in n or "necesito animo" in n:
        animar()
        return True

    if "desahog" in n:
        estado["desahogo"] = True
        hablar("Soy todo oídos, cuéntame. Cuando quieras parar, dime: ya estoy mejor.")
        return True

    if re.search(r"\b(reto|retos|trivia|juguemos)\b|preguntame algo", n):
        trivia()
        return True

    if n == "diario" or re.search(r"\b(mi diario|el diario|diario por voz|diario de voz)\b", n):
        diario()
        return True

    # ---------- charla normal con IA ----------
    indicacion = ""
    if re.search(r"\b(explicame|explica|cuentame|dame ideas|ideas para|que significa|define|"
                 r"resumeme|diferencia entre|redacta|escribe|traduce|como funciona|por que)\b", n):
        indicacion = "Esta vez puedes extenderte hasta seis frases cortas, de forma natural y hablada."
    charlar(texto, historial, indicacion)
    return True


# =====================================================================
#  VENTANA: fondo negro con un orbe animado
# =====================================================================
COLORES = {
    "cargando": "#2a6f97",
    "dormido": "#2a6f97",
    "escuchando": "#19d3ff",
    "pensando": "#ffb703",
    "hablando": "#5ef2ff",
}


def mezcla(hexc, f):
    """Oscurece un color (f entre 0 y 1)."""
    f = max(0.0, min(1.0, f))
    r = int(int(hexc[1:3], 16) * f)
    g = int(int(hexc[3:5], 16) * f)
    b = int(int(hexc[5:7], 16) * f)
    return f"#{r:02x}{g:02x}{b:02x}"


def amplitud_voz(t):
    """Volumen de la voz de Jarvis en este instante (0 a 1)."""
    env = estado["env"]
    if estado["reproduciendo"] and env:
        i = int((t - estado["env_t0"] - 0.08) / 0.033)
        if 0 <= i < len(env):
            return env[i]
        return 0.0
    if estado["reproduciendo"]:
        return 0.5 + 0.35 * math.sin(t * 9) + 0.15 * math.sin(t * 5.3)
    return 0.15


def dibujar(c, w, h, t, modo, nivel, anim):
    """Dibuja un fotograma: solo el orbe, sin texto. 'nivel' va de 0 a 1."""
    c.delete("all")
    color = COLORES.get(modo, COLORES["dormido"])
    cx, cy = w / 2, h / 2
    base = max(30.0, min(w, h) * 0.17)

    objetivo = max(0.0, min(1.0, nivel))
    suave = 0.5 if modo == "hablando" else 0.25
    anim["nivel"] += (objetivo - anim["nivel"]) * suave
    v = anim["nivel"]

    if modo in ("dormido", "cargando"):
        r = base * (0.62 + 0.04 * math.sin(t * 0.9) + 0.25 * v)
        brillo, vel = 0.45 + 0.3 * v, 0.15
    elif modo == "escuchando":
        r = base * (0.85 + 0.9 * v)
        brillo, vel = 0.75 + 0.25 * v, 0.5
    elif modo == "pensando":
        r = base * (0.9 + 0.06 * math.sin(t * 7))
        brillo, vel = 0.85, 2.2
    else:
        r = base * (0.95 + 0.6 * v)
        brillo, vel = 0.7 + 0.3 * v, 1.0
    anim["ang"] = (anim["ang"] + vel * 2.0) % 360

    # resplandor: discos concéntricos que se aclaran hacia el centro
    for i in range(14):
        f = i / 13
        rad = r * (1.9 - 1.15 * f)
        c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                      fill=mezcla(color, brillo * (0.03 + 0.97 * f ** 2.2)), outline="")
    # núcleo brillante
    n = r * 0.33
    c.create_oval(cx - n, cy - n, cx + n, cy + n,
                  fill=mezcla("#e8fbff", 0.55 + 0.4 * brillo), outline="")

    # anillos giratorios
    anillos = [(1.55, 3, 80, 1), (1.85, 2, 120, -1), (2.2, 2, 50, 1)]
    for k, (mult, ancho, largo, sentido) in enumerate(anillos):
        rad = base * mult
        for j in range(3):
            ini_ang = anim["ang"] * sentido * (1 + 0.4 * k) + j * 120
            c.create_arc(cx - rad, cy - rad, cx + rad, cy + rad,
                         start=ini_ang, extent=largo, style="arc",
                         outline=mezcla(color, 0.35 + 0.5 * brillo), width=ancho)
    rad = base * 2.6
    c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad,
                  outline=mezcla(color, 0.18), width=1)


def lanzar_ventana(hilo_logica):
    """Abre la ventana. Devuelve False si no se ha podido abrir."""
    try:
        root = tk.Tk()
        root.title("Jarvis")
        root.configure(bg="black")
        root.geometry("700x700")
        c = tk.Canvas(root, bg="black", highlightthickness=0)
        c.pack(fill="both", expand=True)
    except Exception as e:
        print("No he podido abrir la ventana:", e)
        return False

    anim = {"nivel": 0.0, "ang": 0.0}
    completa = {"si": False}

    def alternar(_=None):
        completa["si"] = not completa["si"]
        root.attributes("-fullscreen", completa["si"])

    def salir_completa(_=None):
        completa["si"] = False
        root.attributes("-fullscreen", False)

    def cerrar():
        estado["cerrar"] = True
        try:
            root.destroy()
        except Exception:
            pass

    root.bind("<F11>", alternar)
    root.bind("<Escape>", salir_completa)
    root.protocol("WM_DELETE_WINDOW", cerrar)

    def tick():
        if estado["cerrar"]:
            cerrar()
            return
        w, h = c.winfo_width(), c.winfo_height()
        t = time.time()
        modo = estado["gui"]
        if estado["reproduciendo"] or t - estado["ultimo_audio"] < 0.35:
            modo = "hablando"
            nivel = amplitud_voz(t)
        elif modo in ("dormido", "escuchando"):
            nivel = min(1.0, estado["nivel"] * 14)
        else:
            nivel = 0.0
        try:
            dibujar(c, w, h, t, modo, nivel, anim)
        except Exception:
            pass
        root.after(33, tick)

    hilo_logica.start()
    tick()
    root.mainloop()
    estado["cerrar"] = True
    return True


# =====================================================================
#  ARRANQUE
# =====================================================================
def logica():
    global whisper
    try:
        print("=" * 60)
        print(" JARVIS")
        print("=" * 60)
        iniciar_voz()
        threading.Thread(target=calentar_modelo, daemon=True).start()
        threading.Thread(target=precalentar_voz, daemon=True).start()

        if SOLO_TEXTO:
            print("Modo texto activado (SOLO_TEXTO = True).")
        elif not VOZ_OK:
            print("No he podido cargar las librerías de voz, así que uso el teclado.")
            print("Detalle:", ERROR_VOZ)
            print("Instálalas con: pip install faster-whisper sounddevice numpy")
        else:
            try:
                print("Micrófono en uso:",
                      sd.query_devices(DISPOSITIVO_ENTRADA, kind="input")["name"])
                entradas = [f"[{i}] {d['name']}" for i, d in enumerate(sd.query_devices())
                            if d["max_input_channels"] > 0]
                print("Micrófonos disponibles:", " | ".join(entradas))
            except Exception:
                print("Micrófono: no se ha podido detectar")
            print(f"Cargando el oído (modelo {WHISPER_MODELO}). La primera vez se "
                  "descarga y tarda un rato...")
            whisper = WhisperModel(WHISPER_MODELO, device="cpu", compute_type="int8",
                                   cpu_threads=min(8, os.cpu_count() or 4))
            list(whisper.transcribe(np.zeros(MUESTREO, dtype="float32"),
                                    language="es", beam_size=1)[0])
            calibrar()

        if HABLAR_EN_VOZ:
            if USAR_ELEVENLABS:
                print("Voz: ElevenLabs (si falla, paso a la de Edge o a la de Windows).")
            elif USAR_VOZ_ONLINE and EDGE_OK:
                print("Voz: Edge (Álvaro). Sin clave de ElevenLabs.")
            else:
                print("Voz: la de Windows.")
        if HABLAR_EN_VOZ and USAR_VOZ_ONLINE and not EDGE_OK:
            print("Falta edge-tts: uso la voz de Windows. Instálalo con: pip install edge-tts")

        if estado["despierto"]:
            hablar(random.choice(SALUDOS))
        else:
            print('Jarvis está dormido. Di: "Jarvis, despierta".')

        seguir = True
        while seguir and not estado["cerrar"]:
            try:
                entregar_recordatorios()
                texto = escuchar()
                if texto is None:
                    continue
                seguir = procesar(texto)
            except KeyboardInterrupt:
                print("\nCerrando Jarvis.")
                break
            except Exception as e:
                print("(Algo ha fallado:", e, ")")
                traceback.print_exc()
    except Exception:
        traceback.print_exc()
    finally:
        estado["cerrar"] = True


def main():
    hilo = threading.Thread(target=logica, daemon=True)
    if USAR_VENTANA and TK_OK:
        if lanzar_ventana(hilo):
            return
    elif USAR_VENTANA and not TK_OK:
        print("No he encontrado tkinter, así que no hay ventana. Sigo en esta pantalla.")
    logica()


if __name__ == "__main__":
    main()
