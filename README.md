# 🕷️ spAIder — Leg Lab (IK + Streamlit + Arduino)

**spAIder** es un proyecto educativo para explorar **cinemática directa (FK)**, **cinemática inversa (IK)** y **trayectorias** de una pierna de robot (coxa–fémur–tibia), y para **controlar servos** vía **Arduino + PCA9685** con una GUI moderna en **Streamlit**.

Incluye explicaciones en lenguaje natural, un **E-STOP** de emergencia, validador de trayectorias (*preflight*) y selector de solución IK (**knee-up / knee-down**).  
Repositorio: https://github.com/joshpineda17/spAIder-.git

---

## ✨ Características principales

- Control de **3 servos MG996R** con un **PCA9685** (canales 13–15).
- GUI en **Streamlit** para controlar manualmente servos o enviar coordenadas `XYZ`.
- Explicaciones integradas sobre la cinemática de la pierna.
- Reproducción de trayectorias (swing + stance) con validación previa (*preflight*).
- Compatible con **Arduino UNO/Nano/MEGA** y **fuente externa de 6 V** para servos.

---

## 🛠️ Tecnologías usadas

- Python 3.9+
- Streamlit (GUI)
- NumPy, Matplotlib (cálculo/visualización)
- PySerial (comunicación serie)
- Hardware: Arduino, PCA9685, servos MG996R

---

## 📋 Requisitos

Archivo `requirements.txt`:

    streamlit
    matplotlib
    numpy
    pyserial

### Crear entorno virtual

**Windows**

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt

**macOS / Linux**

    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

---

## 🔧 Firmware Arduino

1) Abre `spAiderArduino/spAiderArduino.ino` en **Arduino IDE**.  
2) Instala desde **Library Manager**:
   - Adafruit PWM Servo Driver (Adafruit_PWMServoDriver)
   - Adafruit BusIO
3) Velocidad serie en el sketch: **115200 baud**.  
4) Sube el firmware y **cierra el Monitor Serie** (la app usará el puerto COM).

---

## ⚡ Cableado (resumen)

- **PCA9685 → Arduino (UNO)**: `SDA→A4`, `SCL→A5`, `VCC→5V` (lógica), `GND→GND`, `OE→GND`.
- **Servos en PCA9685**: CH13=Coxa, CH14=Fémur, CH15=Tibia.
- **Alimentación servos**: `V+ → 6V` fuente externa, `GND` común con **Arduino** y **PCA9685**.
- Revisa polaridad de los conectores: **GND** (negro/marrón), **V+** (rojo), **PWM** (amarillo/blanco).

> Importante: **no** alimentes servos desde el 5 V del Arduino. Usa **fuente externa 6 V** y **GND común**.

---

## 🚀 Ejecutar la app

Con el **venv activado**:

    streamlit run leg_gui.py

Abre la URL local (por ejemplo `http://localhost:8501`).

**Panel lateral:**
- Selecciona **Puerto COM** correcto (p. ej. `COM3` en Windows) y **115200** baud.
- Botones **Conectar / Desconectar**.
- Ajusta **L1/L2/L3** (mm), **ZERO** y **DIR** si hace falta.
- **E-STOP** disponible siempre.

**Cómo saber el COM en Windows:**  
Administrador de dispositivos → **Puertos (COM y LPT)** → busca tu Arduino (p. ej. “Arduino Uno (COM3)”).  
Si el puerto está en uso, **cierra el Monitor Serie** del IDE o cualquier programa que lo esté usando.

---

## 🔌 Protocolo serie (firmware)

Comandos que entiende el Arduino:

- `S <canal> <grados>` → mueve un servo del PCA9685 en grados (0–180).  
  Ej.: `S 13 90`
- `XYZ <x> <y> <z>` → mueve el pie a esa posición (mm) resolviendo IK.  
  Ej.: `XYZ 120 40 -60`
- `ON`, `OFF`, `CENTER`, `DEMO` → utilidades del sketch.

Desde la **GUI** puedes enviar estos comandos sin teclearlos.

---

## 📐 Matemática (explicación natural)

### Modelo de pierna
Tres articulaciones:
- **Coxa**: giro en planta (X–Y), define el rumbo hacia donde apunta la pierna.
- **Fémur**: movimiento en el plano lateral (R–Z).
- **Tibia**: también en el plano lateral (R–Z).

Longitudes:
- **L1**: avance fijo de la coxa (offset).
- **L2**: fémur.
- **L3**: tibia.

### Cinemática directa (FK)
Con los ángulos mecánicos conocidos:
1. En el plano lateral, fémur y tibia (dos barras) definen **extensión horizontal (R)** y **altura (Z)** del pie.
2. Sumando el avance fijo **L1** al alargamiento del brazo, obtienes la distancia total desde el eje de coxa.
3. Girando esa distancia por el ángulo de la **coxa**, obtienes las coordenadas **X** y **Y** del pie en planta.

### Cinemática inversa (IK)
Dado **(X, Y, Z)**:
1. **Coxa**: calcula el rumbo hacia (X, Y) y alinea la pierna en planta.
2. Proyecta al plano lateral (usa **R** y **Z** relativos a la bisagra del fémur).
3. Resuelve ángulos de **fémur** y **tibia** (ley de cosenos). Hay dos ramas:
   - **Knee-up**: rodilla hacia arriba.
   - **Knee-down**: rodilla hacia abajo.
4. Aplica **límites articulares** para no forzar la mecánica.

---

## ⚙️ Calibración ZERO/DIR y mapeo a PWM

- **ZERO** (por servo): corrige el **desfase mecánico** (qué valor de servo corresponde a tu “cero” geométrico).
- **DIR**: sentido positivo/negativo según el montaje.

Ruta de control:
1. **Slider (0–180° servo)** → aplica **ZERO/DIR** → **ángulo mecánico** coherente.
2. Servo → **ancho de pulso** típico:
   - 0° ≈ **500 µs**
   - 180° ≈ **2500 µs**
3. PCA9685 a 50 Hz usa **ticks 0–4095**: convierte **µs → ticks** y mueve el canal.

Calibración rápida:
1. Pulsa **CENTER** (neutral).
2. Ajusta **ZERO** y **DIR** hasta que la pierna quede centrada.
3. Guarda **preset** (JSON) desde la GUI.

---

## 👣 Trayectorias y preflight

**Generador de paso (ciclo):**
- **Swing (aire)**: el pie avanza en X y describe una **campana** en Z (sube/baja suave).
- **Stance (suelo)**: el pie retrocede en X a **altura casi constante** (simula apoyo).
- **Y** suele mantenerse fijo para simplificar.

**Preflight** valida cada punto:
- **Alcance** (IK tiene solución).
- **Límites** (coxa/fémur/tibia dentro de rango seguro).
- **Suavidad** (sin saltos grandes entre muestras).

Si falla, el player **no arranca** y verás el índice y motivo.

---

## 📂 Estructura del repo

    spAIder-/
    ├─ leg_gui.py                     # App Streamlit (GUI)
    ├─ requirements.txt
    ├─ spAiderArduino/
    │  └─ spAiderArduino.ino          # Firmware Arduino (protocolo S/XYZ/ON/OFF...)
    ├─ README.md
    └─ assets/                        # (opcional) imágenes, diagramas, logo

---

## 🧯 Troubleshooting

1) **La app no abre / “missing ScriptRunContext”**  
   Ejecuta con: `streamlit run leg_gui.py` (no uses `python leg_gui.py`).

2) **No conecta el puerto (COM incorrecto)**  
   Cierra el **Monitor Serie**. Ve a Administrador de dispositivos → Puertos (COM y LPT) y anota el COM (ej. COM3). Selecciónalo en la GUI a **115200** baud.

3) **No se mueven los servos**  
   - PCA9685 alimentado en **V+** con **6 V**.  
   - **GND común** entre fuente, PCA9685 y Arduino.  
   - Conectores servo correctos (GND, V+, PWM).  
   - Servos en **CH13/14/15**.  
   - Librerías Adafruit instaladas, firmware correcto.  
   - Prueba `S 13 90`, `S 14 90`, `S 15 90` desde la pestaña **Control**.

4) **Servos tiemblan / Arduino se reinicia**  
   - Fuente **≥ 3–5 A**.  
   - Cables cortos y de buen calibre.  
   - Reduce longitud/altura del paso o aumenta el periodo (más lento).  
   - Frecuencia player ~**15–20 Hz**.

5) **Preflight falla**  
   - Puntos inalcanzables: reduce **L/H** o ajusta (x0, y0, z0).  
   - Límites demasiado optimistas: ajusta rangos o geometría.  
   - Saltos grandes: sube **resolución** (más puntos) o baja longitud/velocidad.

6) **“ERR XYZ” en el Log**  
   - Formato inválido o punto fuera de alcance. Usa números: `XYZ 120 40 -60`.

7) **El COM se “pierde”**  
   - Desconecta y reconecta USB; espera ~2 s (auto-reset).  
   - Cierra cualquier app que use el puerto.

---

## 🧩 Git y finales de línea (Windows)

`.gitattributes` recomendado:

    * text=auto
    *.py  text eol=lf
    *.ino text eol=lf

Normalizar y subir:

    git add --renormalize .
    git commit -m "Normaliza finales de línea"
    git push

Si el remoto ya tenía archivos y **quieres empezar de 0**, forzar push (⚠️ sobrescribe):

    git push -u origin main --force

---

## 📜 Licencia

Proyecto con fines **educativos**. Puedes usar **MIT** u otra licencia a tu elección.

---

## 📎 Anexos

`.gitignore` recomendado:

    venv/
    __pycache__/
    *.pyc
    .streamlit/
    .vscode/
    .idea/

Comandos Git básicos:

    git init
    git add .
    git commit -m "spAIder: primera versión"
    git branch -M main
    git remote add origin https://github.com/joshpineda17/spAIder-.git
    git push -u origin main
