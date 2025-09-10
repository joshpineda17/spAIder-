import math, time, threading, json
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

# ====== Serie (opcional; solo local) ======
try:
    import serial
    from serial.tools import list_ports
    HAS_SERIAL = True
except Exception:
    HAS_SERIAL = False

st.set_page_config(page_title="spAIder — Leg Lab (Advanced)", layout="wide")

# ====== Estado persistente ======
ss = st.session_state
ss.setdefault("ser", None)
ss.setdefault("log", [])
ss.setdefault("ZERO", [90.0, 90.0, 90.0])  # coxa,fémur,tibia (offsets servo->mecánico)
ss.setdefault("DIR",  [1, -1, -1])        # direcciones (+1 o -1)
ss.setdefault("baud", 115200)

# ====== Parámetros geométricos y límites ======
DEFAULT_L = dict(L1=50.0, L2=80.0, L3=100.0)  # mm
SAFE_MIN = [0, 10, 10]    # límites mecánicos aproximados (grados)
SAFE_MAX = [180, 170, 170]

US_MIN = 500   # μs para 0°
US_MAX = 2500  # μs para 180°
PERIOD_US = 20000  # μs a 50 Hz (PCA9685)
COUNTS = 4096      # 12-bit

# ====== Utilidades geométricas ======
def clamp(v, lo, hi): return max(lo, min(hi, v))

def wrap_deg_0_360(a):
    a = a % 360.0
    if a < 0: a += 360.0
    return a

def fk_xyz(L1,L2,L3, t1_deg, t2_deg, t3_deg):
    """Cinemática directa (x,y,z) a partir de ángulos mecánicos t1,t2,t3 en grados."""
    t1 = math.radians(t1_deg); t2 = math.radians(t2_deg); t3 = math.radians(t3_deg)
    r_xy = L2*math.cos(t2) + L3*math.cos(t2+t3)   # proyección en planta de fémur+tibia
    z    = L2*math.sin(t2) + L3*math.sin(t2+t3)   # altura
    r_tot = L1 + r_xy                              # L1 adelanta el pie respecto al eje de coxa
    x = r_tot*math.cos(t1)
    y = r_tot*math.sin(t1)
    return x,y,z

def ik_angles_variant(L1,L2,L3, x,y,z, knee_up=True):
    """Cinemática inversa con dos ramas: knee_up (rodilla “hacia arriba”) y knee_down (hacia abajo)."""
    t1 = math.degrees(math.atan2(y, x))          # giro de coxa en planta
    rxy = math.sqrt(x*x + y*y) - L1              # “radio útil” desde la bisagra del fémur
    if rxy < 0: rxy = 0.0
    D = (rxy*rxy + z*z - L2*L2 - L3*L3)/(2.0*L2*L3)
    D = clamp(D, -1.0, 1.0)                      # si quedaba fuera por redondeos, lo acotamos
    t3r = math.acos(D)
    if not knee_up:
        t3r = -t3r
    t3 = math.degrees(t3r)
    t2 = math.degrees(math.atan2(z, rxy) - math.atan2(L3*math.sin(t3r), L2 + L3*math.cos(t3r)))
    return (t1, t2, t3)

def ik_angles(L1,L2,L3, x,y,z):
    return ik_angles_variant(L1,L2,L3, x,y,z, knee_up=True)

def servo_to_mech(idx, servo_deg):
    return (servo_deg - ss.ZERO[idx]) * (1 if ss.DIR[idx]==1 else -1)

def mech_to_servo(idx, mech_deg):
    return ss.ZERO[idx] + ss.DIR[idx]*mech_deg

def deg_to_us(servo_deg, us_min=US_MIN, us_max=US_MAX):
    """Convierte grados de servo (0–180) a microsegundos."""
    return us_min + (us_max - us_min) * (servo_deg/180.0)

def us_to_counts(us):
    """Convierte microsegundos a “ticks” 12-bit del PCA9685."""
    return int(round(us * COUNTS / PERIOD_US))

# ====== Serie helpers ======
def list_serial_ports():
    if not HAS_SERIAL: return []
    return [p.device for p in list_ports.comports()]

def send_line(line: str, read_back=True):
    ser = ss.ser
    if ser is None:
        ss.log.append("⛔ No conectado.")
        return False
    try:
        if not line.endswith("\n"): line += "\n"
        ser.write(line.encode("utf-8"))
        ss.log.append("→ " + line.strip())
        if read_back:
            t0 = time.time()
            while time.time()-t0 < 0.25:
                data = ser.read_all()
                if data:
                    for part in data.decode(errors="replace").splitlines():
                        ss.log.append("← " + part.strip())
                time.sleep(0.01)
        return True
    except Exception as e:
        ss.log.append(f"[ERR] {e}")
        return False

# ====== Recursos thread-safe para el player ======
@st.cache_resource
def get_player_resources():
    return {
        "run_event": threading.Event(),
        "lock": threading.Lock(),
    }

def estop(res):
    """Botón rojo: detiene el hilo y apaga los servos."""
    try:
        if "run_event" in res and res["run_event"].is_set():
            res["run_event"].clear()
    except:
        pass
    send_line("OFF")

# ====== Logo spAIder (SVG inline) ======
def render_logo():
    st.markdown(
        """
<div style="display:flex;align-items:center;gap:14px;margin:-8px 0 8px 0;">
  <svg width="56" height="56" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <linearGradient id="g1" x1="0" x2="1">
        <stop offset="0%" stop-color="#7c3aed"/>
        <stop offset="100%" stop-color="#22d3ee"/>
      </linearGradient>
    </defs>
    <circle cx="32" cy="32" r="14" fill="url(#g1)" />
    <!-- patitas -->
    <line x1="10" y1="18" x2="24" y2="26" stroke="#7c3aed" stroke-width="3" />
    <line x1="54" y1="18" x2="40" y2="26" stroke="#22d3ee" stroke-width="3" />
    <line x1="10" y1="46" x2="24" y2="38" stroke="#7c3aed" stroke-width="3" />
    <line x1="54" y1="46" x2="40" y2="38" stroke="#22d3ee" stroke-width="3" />
  </svg>
  <div>
    <div style="font-size:28px;font-weight:800;line-height:1;">spAIder — Leg Lab</div>
    <div style="opacity:.7;line-height:1.2;">Cinemática, trayectorias y control didáctico</div>
  </div>
</div>
        """,
        unsafe_allow_html=True
    )

# ====== Sidebar ======
with st.sidebar:
    st.title("Panel spAIder")
    st.caption("Proyecto educativo controlado por IA 🧠")

    st.subheader("Conexión serie (opcional)")
    if HAS_SERIAL:
        ports = list_serial_ports() or ["COM3"]
        port = st.selectbox("Puerto", ports, index=0)
        ss.baud = st.selectbox("Baudios", [115200, 57600, 38400, 19200, 9600], index=0)
        c1, c2 = st.columns(2)
        if c1.button("Conectar", use_container_width=True, disabled=ss.ser is not None):
            try:
                ser = serial.Serial(port, baudrate=ss.baud, timeout=0.2)
                time.sleep(2.0)  # auto-reset UNO
                ss.ser = ser
                ss.log.append(f"[OK] Conectado a {port} @ {ss.baud}")
                send_line("HELLO")
            except Exception as e:
                ss.ser = None
                ss.log.append(f"[ERR] {e}")
                st.error(str(e))
        if c2.button("Desconectar", use_container_width=True, disabled=ss.ser is None):
            try:
                if ss.ser: ss.ser.close()
                ss.ser = None
                ss.log.append("[OK] Desconectado.")
            except Exception as e:
                ss.log.append(f"[ERR] {e}")
                st.error(str(e))
    else:
        st.info("Instala pyserial para usar COM (local):  pip install pyserial")

    st.subheader("Geometría (mm)")
    L1 = st.number_input("L1 (coxa)", value=DEFAULT_L["L1"], step=1.0, key="L1_val")
    L2 = st.number_input("L2 (fémur)", value=DEFAULT_L["L2"], step=1.0, key="L2_val")
    L3 = st.number_input("L3 (tibia)", value=DEFAULT_L["L3"], step=1.0, key="L3_val")

    st.subheader("Calibración servo→mecánico")
    z0,z1,z2 = st.columns(3)
    ss.ZERO[0] = z0.number_input("ZERO coxa", value=float(ss.ZERO[0]), step=1.0)
    ss.ZERO[1] = z1.number_input("ZERO fémur", value=float(ss.ZERO[1]), step=1.0)
    ss.ZERO[2] = z2.number_input("ZERO tibia", value=float(ss.ZERO[2]), step=1.0)
    d0,d1,d2 = st.columns(3)
    ss.DIR[0]  = d0.selectbox("DIR coxa",  [1,-1], index=0 if ss.DIR[0]==1 else 1)
    ss.DIR[1]  = d1.selectbox("DIR fémur", [1,-1], index=1)
    ss.DIR[2]  = d2.selectbox("DIR tibia", [1,-1], index=1)

    # ---- E-STOP global siempre visible ----
    res_sidebar = get_player_resources()
    st.divider()
    if st.button("🛑 E-STOP (OFF + Stop player)", type="primary", use_container_width=True):
        estop(res_sidebar)
        st.success("E-STOP ejecutado")

    # ---- Presets (guardar/cargar) ----
    st.subheader("Presets")
    cfg = {"L":[L1, L2, L3], "ZERO": ss.ZERO, "DIR": ss.DIR, "baud": ss.baud}
    st.download_button("💾 Descargar preset", data=json.dumps(cfg, indent=2),
                       file_name="spAIder_preset.json", mime="application/json", use_container_width=True)
    up = st.file_uploader("📤 Cargar preset", type=["json"])
    if up is not None:
        try:
            data = json.loads(up.read().decode("utf-8"))
            L1, L2, L3 = data.get("L", [L1, L2, L3])
            ss.ZERO = data.get("ZERO", ss.ZERO)
            ss.DIR  = data.get("DIR",  ss.DIR)
            ss.baud = data.get("baud", ss.baud)
            st.success("Preset cargado. Ajusta sliders si es necesario.")
        except Exception as e:
            st.error(f"Preset inválido: {e}")

# ====== Header + logo ======
render_logo()

tabs = st.tabs(["🎮 Control", "🧮 IK y Visual", "🦶 Trayectoria (Player)", "🗺️ Workspace", "📜 Log"])

# === Tab Control ===
with tabs[0]:
    st.subheader("Comandos rápidos")
    cA, cB, cC, cD = st.columns(4)
    if cA.button("ON", use_container_width=True): send_line("ON")
    if cB.button("OFF", use_container_width=True): send_line("OFF")
    if cC.button("CENTER", use_container_width=True): send_line("CENTER")
    if cD.button("DEMO", use_container_width=True): send_line("DEMO")

    st.divider()
    st.subheader("Enviar S (servo grados)")
    col = st.columns(3)
    s13 = col[0].slider("CH13 Coxa", 0, 180, 90, 1)
    s14 = col[1].slider("CH14 Fémur", 0, 180, 90, 1)
    s15 = col[2].slider("CH15 Tibia", 0, 180, 90, 1)

    # Ejemplo numérico para explicar el mapeo (texto natural)
    t1_m = servo_to_mech(0, s13)
    t2_m = servo_to_mech(1, s14)
    t3_m = servo_to_mech(2, s15)
    us13 = deg_to_us(s13); us14 = deg_to_us(s14); us15 = deg_to_us(s15)
    ct13 = us_to_counts(us13); ct14 = us_to_counts(us14); ct15 = us_to_counts(us15)

    with st.expander("¿Qué hace exactamente este control? Explicación simple con tus números"):
        st.write(
            "Cuando mueves un **slider**, estás dando un ángulo del servo en grados (0 a 180). "
            "Como cada servo puede estar montado con un pequeño desfase, primero le restamos su **ZERO** "
            f"y aplicamos la **dirección** (1 o −1). Con tus sliders actuales eso se traduce en:\n"
            f"- Coxa: el servo está en {s13:.0f}°, y después de ZERO/DIR queda un ángulo mecánico de {t1_m:.1f}°.\n"
            f"- Fémur: servo {s14:.0f}° → mecánico {t2_m:.1f}°.\n"
            f"- Tibia: servo {s15:.0f}° → mecánico {t3_m:.1f}°.\n\n"
            "Para que el PCA9685 pueda moverlos, esos grados se convierten a **microsegundos** de pulso: "
            f"con el mapeo típico, ahora mismo serían {us13:.0f} μs, {us14:.0f} μs y {us15:.0f} μs. "
            "El PCA9685 trabaja en “ticks” de 0 a 4095 a 50 Hz, y esos pulsos equivalen a "
            f"{ct13} ticks, {ct14} ticks y {ct15} ticks respectivamente. "
            "En resumen: *slider → (ZERO/DIR) → grados mecánicos → μs → ticks*."
        )

    if st.button("➡️ Enviar S 13/14/15", use_container_width=True):
        ok = send_line(f"S 13 {s13}") and send_line(f"S 14 {s14}") and send_line(f"S 15 {s15}")
        if not ok: st.warning("No conectado o error al enviar.")

    st.divider()
    st.subheader("Enviar XYZ (mm)")
    cx, cy, cz = st.columns(3)
    X = cx.number_input("x", value=120.0, step=1.0)
    Y = cy.number_input("y", value=40.0,  step=1.0)
    Z = cz.number_input("z", value=-60.0, step=1.0)
    if st.button("➡️ Enviar XYZ", use_container_width=True):
        if not send_line(f"XYZ {X} {Y} {Z}"):
            st.warning("No conectado o error al enviar.")

    with st.expander("¿Qué comandos entiende el Arduino?"):
        st.write(
            "• `S <canal> <grados>`: mueve un servo concreto del PCA9685 al ángulo indicado.\n"
            "• `XYZ <x> <y> <z>`: mueve el **pie** a una posición en milímetros; el Arduino resuelve la IK.\n"
            "• `ON` / `OFF` / `CENTER` / `DEMO`: utilidades generales del sketch."
        )

# === Tab IK y Visual ===
with tabs[1]:
    st.subheader("IK (resuelve ángulos) y visualiza")
    form = st.columns(4)
    Xv = form[0].number_input("x (mm)", value=120.0, step=1.0)
    Yv = form[1].number_input("y (mm)", value=40.0,  step=1.0)
    Zv = form[2].number_input("z (mm)", value=-60.0, step=1.0)
    knee_mode_tab = form[3].radio("Solución", ["Knee-Up", "Knee-Down"])
    knee_up_tab = (knee_mode_tab == "Knee-Up")

    # Explicación natural con ejemplo de los valores introducidos
    rxy_demo = max(0.0, math.sqrt(Xv*Xv + Yv*Yv) - L1)
    D_demo = (rxy_demo*rxy_demo + Zv*Zv - L2*L2 - L3*L3) / (2.0*L2*L3)
    D_demo = clamp(D_demo, -1.0, 1.0)

    with st.expander("¿Cómo calcula spAIder los ángulos a partir de X, Y y Z?"):
        st.write(
            "Primero calculamos cuánto debe girar la **coxa** mirando la planta: "
            f"tomamos Y y X y medimos el ángulo que forman con el eje X. Con tus valores, eso da aproximadamente "
            f"{math.degrees(math.atan2(Yv,Xv)):.2f}°. "
            "Luego nos quedamos con la distancia horizontal desde la cadera hasta el pie, restando L1, y con la altura Z. "
            f"Con tus números, esa distancia radial sale {rxy_demo:.1f} mm.\n\n"
            "Con esa distancia y la altura vemos si el pie está **al alcance** de fémur+tibia; si lo está, hay "
            "dos maneras de doblar la rodilla: una con la rodilla “hacia arriba” (knee-up) y otra “hacia abajo” "
            "(knee-down). Tú eliges cuál quiere usar el cálculo. A partir de ahí, el sistema determina "
            "los ángulos de fémur y tibia que colocan el pie donde pediste."
        )

    if st.button("Resolver IK"):
        resik = ik_angles_variant(L1,L2,L3, Xv,Yv,Zv, knee_up=knee_up_tab)
        if not resik:
            st.error("Fuera de alcance o IK inválida.")
        else:
            t1,t2,t3 = resik
            t1n = wrap_deg_0_360(t1)
            ok_lim = (SAFE_MIN[0] <= t1n <= SAFE_MAX[0] and
                      SAFE_MIN[1] <= t2  <= SAFE_MAX[1] and
                      SAFE_MIN[2] <= t3  <= SAFE_MAX[2])
            if not ok_lim:
                st.warning("Se encontró una solución, pero queda fuera de límites seguros. Ajusta pose/longitudes.")
            st.success(f"Ángulos mecánicos: coxa={t1:.1f}°, fémur={t2:.1f}°, tibia={t3:.1f}°")
            x,y,z = fk_xyz(L1,L2,L3, t1,t2,t3)
            st.caption(f"Comprobación directa (FK): x={x:.1f}, y={y:.1f}, z={z:.1f}")

            colA, colB = st.columns(2)
            with colA:
                st.markdown("**Vista superior (X–Y)**")
                fig, ax = plt.subplots(figsize=(4.4,4.4))
                ax.set_aspect("equal","box"); reach = L1+L2+L3
                ax.set_xlim(-reach, reach); ax.set_ylim(-reach, reach); ax.grid(True, alpha=0.3)
                hip = (L1*math.cos(math.radians(t1)), L1*math.sin(math.radians(t1)))
                knee_r = L2*math.cos(math.radians(t2))
                knee = ((L1+knee_r)*math.cos(math.radians(t1)), (L1+knee_r)*math.sin(math.radians(t1)))
                ax.plot([0,hip[0]],[0,hip[1]], lw=3)
                ax.plot([hip[0],knee[0]],[hip[1],knee[1]], lw=4)
                ax.plot([knee[0],x],[knee[1],y], lw=4)
                ax.scatter([0,hip[0],knee[0],x],[0,hip[1],knee[1],y], s=40)
                ax.set_xlabel("X [mm]"); ax.set_ylabel("Y [mm]")
                st.pyplot(fig)

            with colB:
                st.markdown("**Vista lateral (R–Z)**")
                fig2, ax2 = plt.subplots(figsize=(4.4,4.4))
                ax2.set_aspect("equal","box"); reach2 = L2+L3
                ax2.set_xlim(-reach2, reach2); ax2.set_ylim(-reach2, reach2); ax2.grid(True, alpha=0.3)
                knee_s = (L2*math.cos(math.radians(t2)), L2*math.sin(math.radians(t2)))
                foot_s = (L2*math.cos(math.radians(t2))+L3*math.cos(math.radians(t2+t3)),
                          L2*math.sin(math.radians(t2))+L3*math.sin(math.radians(t2+t3)))
                ax2.plot([0,knee_s[0]],[0,knee_s[1]], lw=4)
                ax2.plot([knee_s[0],foot_s[0]],[knee_s[1],foot_s[1]], lw=4)
                ax2.scatter([0,knee_s[0],foot_s[0]],[0,knee_s[1],foot_s[1]], s=40)
                ax2.set_xlabel("R [mm]"); ax2.set_ylabel("Z [mm]")
                st.pyplot(fig2)

            if st.button("➡️ Enviar XYZ"):
                if not send_line(f"XYZ {Xv} {Yv} {Zv}"):
                    st.warning("No conectado o error al enviar.")

# === Tab Trayectoria (Player) ===
with tabs[2]:
    st.subheader("Generador de paso (trayectoria del pie)")
    res = get_player_resources()  # Event + Lock

    c0, c1, c2 = st.columns(3)
    x0 = c0.number_input("x neutro (mm)", value=120.0, step=1.0)
    y0 = c1.number_input("y fijo (mm)",  value=40.0,  step=1.0)
    z0 = c2.number_input("z suelo (mm)", value=-60.0, step=1.0)

    c3, c4, c5 = st.columns(3)
    step_len = c3.number_input("Longitud paso L (mm)", value=60.0, min_value=1.0, step=1.0)
    step_h   = c4.number_input("Altura paso H (mm)",   value=35.0, min_value=1.0, step=1.0)
    period   = c5.number_input("Periodo (s/ciclo)",     value=1.2,  min_value=0.2, step=0.1)

    knee_mode = st.radio("Solución IK", ["Knee-Up", "Knee-Down"], horizontal=True)
    knee_up = (knee_mode == "Knee-Up")

    st.caption("La mitad del ciclo el pie va en el aire (sube z), y la otra mitad vuelve sobre el suelo (z≈constante). y permanece fijo.")
    traj_samples = st.slider("Resolución (puntos/ciclo)", 50, 800, 200, 10)

    # Previsualización de la trayectoria (no animada)
    t = np.linspace(0, 1, traj_samples, endpoint=False)
    x_traj = np.empty_like(t); z_traj = np.empty_like(t); y_traj = np.full_like(t, y0)
    for i, ph in enumerate(t):
        if ph < 0.5:  # swing
            s = ph/0.5
            x_traj[i] = x0 - step_len/2 + step_len*s
            z_traj[i] = z0 + step_h * math.sin(math.pi*s)  # campana suave
        else:         # stance
            s = (ph-0.5)/0.5
            x_traj[i] = x0 + step_len/2 - step_len*s
            z_traj[i] = z0

    colP1, colP2 = st.columns(2)
    with colP1:
        st.markdown("**Top (X–Y)**")
        fig, ax = plt.subplots(figsize=(4.4,4.4))
        ax.set_aspect("equal","box"); reach = L1+L2+L3
        ax.set_xlim(-reach, reach); ax.set_ylim(-reach, reach); ax.grid(True, alpha=0.3)
        ax.plot(x_traj, y_traj, lw=2)
        ax.scatter([x0-step_len/2, x0+step_len/2], [y0, y0], s=25)
        ax.set_xlabel("X [mm]"); ax.set_ylabel("Y [mm]")
        st.pyplot(fig)

    with colP2:
        st.markdown("**Side (R–Z)**")
        r_traj = np.sqrt(x_traj**2 + y_traj**2) - L1
        fig2, ax2 = plt.subplots(figsize=(4.4,4.0))
        ax2.plot(r_traj, z_traj, lw=2); ax2.grid(True, alpha=0.3)
        ax2.set_xlabel("R [mm]"); ax2.set_ylabel("Z [mm]")
        st.pyplot(fig2)

    # Explicación natural con números concretos
    hz = 20.0
    dt = 1.0/hz
    avg_vx_swing = step_len / (0.5*period) if period>0 else 0.0
    with st.expander("¿Qué está haciendo exactamente el generador de pasos?"):
        st.write(
            "Dividimos el ciclo en dos mitades: en la primera el pie avanza desde "
            f"{x0 - step_len/2:.1f} mm hasta {x0 + step_len/2:.1f} mm elevándose hasta unos {step_h:.1f} mm sobre el suelo; "
            "en la segunda vuelve hacia atrás sobre el suelo manteniendo la altura en torno a z₀, para simular apoyo. "
            f"Enviamos comandos {int(hz)} veces por segundo (cada {dt:.3f} s). "
            f"Con tus parámetros, la velocidad media horizontal del pie mientras va en el aire es aproximadamente "
            f"{avg_vx_swing:.1f} mm/s. Si la fuente sufre, puedes bajar la resolución o el periodo."
        )

    # ====== Preflight: IK + límites + suavidad ======
    def preflight_traj(L1,L2,L3, x_traj, y_traj, z_traj, safe_min, safe_max, knee_up=True):
        bad = []
        for i,(xx,yy,zz) in enumerate(zip(x_traj, y_traj, z_traj)):
            resik = ik_angles_variant(L1,L2,L3, xx,yy,zz, knee_up=knee_up)
            if not resik:
                bad.append((i, "IK"))   # fuera de alcance
                continue
            t1,t2,t3 = resik
            t1n = wrap_deg_0_360(t1)
            if not (safe_min[0] <= t1n <= safe_max[0] and
                    safe_min[1] <= t2  <= safe_max[1] and
                    safe_min[2] <= t3  <= safe_max[2]):
                bad.append((i, "Límites"))
        return bad

    def too_jerky(x_traj, y_traj, z_traj, max_delta=8.0):
        dx = np.diff(x_traj, prepend=x_traj[0])
        dy = np.diff(y_traj, prepend=y_traj[0])
        dz = np.diff(z_traj, prepend=z_traj[0])
        step = np.sqrt(dx*dx + dy*dy + dz*dz)
        spikes = np.where(step > max_delta)[0]
        return spikes.tolist()

    with st.expander("¿Por qué hacemos un chequeo previo?"):
        st.write(
            "Antes de arrancar, comprobamos tres cosas en cada punto de la trayectoria: "
            "1) que el pie esté al alcance de las barras, "
            "2) que los ángulos no se salgan de los límites de seguridad, "
            "y 3) que no existan saltos bruscos entre un punto y el siguiente (para no castigar los servos). "
            "Si algo falla, te avisamos en qué muestra ocurre."
        )

    # ====== Player en hilo (NO usa st.session_state dentro) ======
    def player_loop(run_event, ser, lock, x_traj, y_traj, z_traj, x0, y0, z0, hz=20):
        dt_local = 1.0 / float(hz)
        N = len(x_traj)
        idx = 0
        def write_line(line: str):
            if not ser: return
            if not line.endswith("\n"): line += "\n"
            try:
                with lock:
                    ser.write(line.encode("utf-8"))
            except Exception:
                pass
        while run_event.is_set():
            j = idx % N
            X = float(x_traj[j]); Y = float(y_traj[j]); Z = float(z_traj[j])
            write_line(f"XYZ {X} {Y} {Z}")
            if (j % 10) == 0:  # pequeño “ping” opcional
                write_line("READY")
            idx += 1
            time.sleep(dt_local)
        # Al parar: postura neutra
        write_line(f"XYZ {x0} {y0} {z0}")

    # ---- Botones Start/Stop con preflight ----
    col_start, col_stop = st.columns(2)
    if col_start.button("▶️ Start (20 Hz)", disabled=get_player_resources()["run_event"].is_set()):
        bad = preflight_traj(L1,L2,L3, x_traj, y_traj, z_traj, SAFE_MIN, SAFE_MAX, knee_up=knee_up)
        spikes = too_jerky(x_traj, y_traj, z_traj, max_delta=8.0)
        if bad:
            st.error(f"El chequeo previo falló en {len(bad)} puntos (ej. índice {bad[0][0]}: {bad[0][1]}). "
                     "Reduce la longitud/altura del paso o ajusta la postura neutra.")
        elif spikes:
            st.warning(f"Se detectaron {len(spikes)} saltos bruscos (>8 mm) (ej. índice {spikes[0]}). "
                       "Aumenta la resolución o baja la longitud del paso o la velocidad.")
        elif ss.ser is None:
            st.warning("Conéctate por COM primero.")
        else:
            res_play = get_player_resources()
            res_play["run_event"].set()
            th = threading.Thread(
                target=player_loop,
                args=(res_play["run_event"], ss.ser, res_play["lock"],
                      x_traj, y_traj, z_traj, x0, y0, z0, 20),
                daemon=True
            )
            th.start()
            ss.log.append("[PLAY] Reproduciendo trayectoria…")

    if col_stop.button("⏹ Stop", disabled=not get_player_resources()["run_event"].is_set()):
        get_player_resources()["run_event"].clear()
        ss.log.append("[PLAY] Stop solicitado.")

# === Tab Workspace ===
with tabs[3]:
    st.subheader("Espacio de trabajo (R–Z) y huella Top (X–Y)")
    n2 = st.slider("Resolución θ2", 40, 200, 120, 10)
    n3 = st.slider("Resolución θ3", 40, 200, 120, 10)
    t2_vals = np.linspace(math.radians(SAFE_MIN[1]), math.radians(SAFE_MAX[1]), n2)
    t3_vals = np.linspace(math.radians(SAFE_MIN[2]), math.radians(SAFE_MAX[2]), n3)
    R, Z = [], []
    XYx, XYy = [], []
    for t2 in t2_vals:
        for t3 in t3_vals:
            r_xy = L2*math.cos(t2) + L3*math.cos(t2+t3)
            z    = L2*math.sin(t2) + L3*math.sin(t2+t3)
            r_tot = L1 + r_xy
            # barrido razonable de coxa
            for t1_deg in np.linspace(SAFE_MIN[0], SAFE_MAX[0], 36):
                t1 = math.radians(t1_deg)
                x = r_tot*math.cos(t1); y = r_tot*math.sin(t1)
                XYx.append(x); XYy.append(y)
            R.append(max(0.0, r_tot - L1))
            Z.append(z)
    colW1, colW2 = st.columns(2)
    with colW1:
        st.markdown("**Side (R–Z) alcance**")
        fig, ax = plt.subplots(figsize=(4.6,4.2))
        ax.scatter(R, Z, s=2, alpha=0.6)
        ax.grid(True, alpha=0.3)
        ax.set_xlabel("R [mm]"); ax.set_ylabel("Z [mm]")
        st.pyplot(fig)
    with colW2:
        st.markdown("**Top (X–Y) huella de alcance**")
        fig2, ax2 = plt.subplots(figsize=(4.6,4.6))
        ax2.set_aspect("equal","box")
        ax2.scatter(XYx, XYy, s=1.5, alpha=0.5)
        reach = L1+L2+L3
        ax2.set_xlim(-reach, reach); ax2.set_ylim(-reach, reach)
        ax2.grid(True, alpha=0.3)
        ax2.set_xlabel("X [mm]"); ax2.set_ylabel("Y [mm]")
        st.pyplot(fig2)

    with st.expander("¿Qué me está mostrando este mapa?"):
        st.write(
            "Para estimar el **alcance**, probamos muchas combinaciones de fémur y tibia dentro de sus límites "
            "y calculamos dónde quedaría el pie en un corte lateral (R–Z). Eso te dice qué alturas y distancias "
            "son razonables. Luego giramos la coxa en un rango seguro para dibujar la **huella en planta (X–Y)**. "
            "Si reduces las longitudes o los límites, la nube de puntos se encoge; si los aumentas, crece."
        )

# === Tab Log ===
with tabs[4]:
    st.subheader("Tráfico serie (local)")
    if st.button("Actualizar log"):
        if ss.ser:
            data = ss.ser.read_all()
            if data:
                for part in data.decode(errors="replace").splitlines():
                    ss.log.append("← " + part.strip())
    st.text_area("Log", value="\n".join(ss.log[-400:]), height=260)
