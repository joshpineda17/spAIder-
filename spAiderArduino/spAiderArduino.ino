/*
  Canales: Coxa=13, Femur=14, Tibia=15
  
  Comandos (una línea por comando):
    HELLO
    ON
    OFF            -> corta PWM (servos relajados)
    CENTER         -> centra 3 servos (1500us)
    DEMO           -> mini secuencia de prueba
    ALL 1500
    ALL_SWEEP
    P 13 1500      -> pulso directo (us)
    S 14 90        -> ángulo 0–180
    ZERO 1 95      -> idx: 0=coxa,1=fémur,2=tibia
    DIR  2 -1      -> invierte sentido (+1/-1)
    XYZ 120 40 -60 -> IK cartesiano (mm)
*/

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm(0x40);

// ======== HARDWARE ========
const uint8_t CH_COXA  = 13;
const uint8_t CH_FEMUR = 14;
const uint8_t CH_TIBIA = 15;

const uint16_t SAFE_MIN_US = 600;
const uint16_t SAFE_MAX_US = 2400;

// Límites/Mapeos por eje (0=coxa,1=fémur,2=tibia)
uint16_t SERVO_MIN_US[3] = {600, 600, 600};
uint16_t SERVO_MAX_US[3] = {2400,2400,2400};
float    ZERO_DEG[3]     = {90,  90,  90};
int      DIR[3]          = {+1,  -1,  -1};
float    MIN_DEG[3]      = {0,   10,  10};
float    MAX_DEG[3]      = {180, 170, 170};

// Geometría pierna (mm)
float L1=50, L2=80, L3=100;

// Estado
bool RUN  = true;   // enciende movimientos prolongados si los hubiera
bool HOLD = false;  // quieto centrado

// ======== UTILS ========
inline uint16_t clampUS(uint16_t us){
  if (us < SAFE_MIN_US) return SAFE_MIN_US;
  if (us > SAFE_MAX_US) return SAFE_MAX_US;
  return us;
}
inline float clampf(float v, float lo, float hi){
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}
inline float rad2deg(float r){ return r * 180.0 / PI; }

void writeUS(uint8_t ch, uint16_t us){ pwm.writeMicroseconds(ch, clampUS(us)); }
void centerAll(){ writeUS(CH_COXA,1500); writeUS(CH_FEMUR,1500); writeUS(CH_TIBIA,1500); }
void allOff(){ for (int ch=0; ch<16; ch++) pwm.setPWM(ch, 0, 0); } // corta PWM

void writeServoDeg(uint8_t ch_hw, uint8_t idx, float deg){
  deg = clampf(deg, 0, 180);
  float us = SERVO_MIN_US[idx] + (SERVO_MAX_US[idx]-SERVO_MIN_US[idx]) * (deg/180.0);
  writeUS(ch_hw, (uint16_t)us);
}
void setJoint(uint8_t ch_hw, uint8_t idx, float deg_mech){
  float deg_servo = DIR[idx]*deg_mech + ZERO_DEG[idx];
  deg_servo = clampf(deg_servo, MIN_DEG[idx], MAX_DEG[idx]);
  writeServoDeg(ch_hw, idx, deg_servo);
}

// ======== IK ========
bool legIK(float x, float y, float z, float &cx, float &fm, float &tb){
  float t1  = atan2(y, x);
  float rxy = sqrt(x*x + y*y) - L1; if (rxy < 0) rxy = 0;
  float d2  = rxy*rxy + z*z;
  float D   = (d2 - L2*L2 - L3*L3) / (2.0 * L2 * L3);
  D = clampf(D, -1, 1);
  float t3 = acos(D);
  float t2 = atan2(z, rxy) - atan2(L3*sin(t3), L2 + L3*cos(t3));
  cx = rad2deg(t1); fm = rad2deg(t2); tb = rad2deg(t3);
  return !(isnan(cx) || isnan(fm) || isnan(tb));
}
void setLegIK(float x, float y, float z){
  float cx,fm,tb; if (legIK(x,y,z,cx,fm,tb)){
    setJoint(CH_COXA,0,cx); setJoint(CH_FEMUR,1,fm); setJoint(CH_TIBIA,2,tb);
  }
}

// ======== DEMO BREVE ========
void demo(){
  float X=120, Y=40, Z=-60;
  setLegIK(X,Y,Z);      delay(220);
  setLegIK(X,Y,Z-22);   delay(220);
  setLegIK(X+24,Y,Z-22);delay(220);
  setLegIK(X+24,Y,Z-60);delay(220);
  setLegIK(X,Y,Z-60);   delay(220);
  setLegIK(X,Y,Z);      delay(220);
}

// ======== PARSER ========
// parsea "a b c" a 3 floats (sin sscanf)
bool parse3Floats(String s, float &a, float &b, float &c){
  s.trim();
  s.replace(',', '.');         // admite coma decimal
  int i1 = s.indexOf(' ');
  if (i1 < 0) return false;
  int i2 = s.indexOf(' ', i1+1);
  if (i2 < 0) return false;
  a = s.substring(0, i1).toFloat();
  b = s.substring(i1+1, i2).toFloat();
  c = s.substring(i2+1).toFloat();
  return true;
}
String readLine(){
  String s = Serial.readStringUntil('\n'); s.trim(); return s;
}

// ======== SETUP / LOOP ========
void setup(){
  Serial.begin(115200);
  Wire.begin();
  pwm.begin();
  pwm.setOscillatorFrequency(27000000); // clones
  pwm.setPWMFreq(50);
  delay(10);
  centerAll();
  Serial.println(F("READY"));
}

void loop(){
  if (!Serial.available()) return;
  String cmd = readLine();
  if (!cmd.length()) return;

  String up = cmd; up.toUpperCase();

  if (up == "HELLO")  { Serial.println(F("OK READY")); return; }
  if (up == "ON")     { RUN=true; HOLD=false; pwm.setPWMFreq(50); centerAll(); Serial.println(F("OK ON")); return; }
  if (up == "OFF")    { RUN=false; HOLD=false; allOff(); Serial.println(F("OK OFF")); return; }
  if (up == "CENTER") { RUN=false; HOLD=true; centerAll(); Serial.println(F("OK CENTER")); return; }
  if (up == "DEMO")   { RUN=true;  HOLD=false; demo(); Serial.println(F("OK DEMO")); return; }

  if (up.startsWith("ALL_SWEEP")){
    for(int ch=0; ch<16; ch++) writeUS(ch,1500); delay(350);
    for(int ch=0; ch<16; ch++) writeUS(ch,1000); delay(280);
    for(int ch=0; ch<16; ch++) writeUS(ch,2000); delay(280);
    for(int ch=0; ch<16; ch++) writeUS(ch,1500); delay(350);
    Serial.println(F("OK ALL_SWEEP")); return;
  }

  if (up.startsWith("ALL ")){         // ALL us
    int us = cmd.substring(4).toInt();
    for (int ch=0; ch<16; ch++) writeUS(ch, us);
    Serial.println(F("OK ALL")); return;
  }

  if (up.startsWith("P ")){           // P ch us
    int sp1 = cmd.indexOf(' '), sp2 = cmd.indexOf(' ', sp1+1);
    int ch = cmd.substring(sp1+1, sp2).toInt();
    int us = cmd.substring(sp2+1).toInt();
    writeUS(ch, us);
    Serial.println(F("OK P")); return;
  }

  if (up.startsWith("S ")){           // S ch ang
    int sp1 = cmd.indexOf(' '), sp2 = cmd.indexOf(' ', sp1+1);
    int ch  = cmd.substring(sp1+1, sp2).toInt();
    int ang = cmd.substring(sp2+1).toInt();
    if (ch==CH_COXA)       writeServoDeg(ch,0,ang);
    else if (ch==CH_FEMUR) writeServoDeg(ch,1,ang);
    else if (ch==CH_TIBIA) writeServoDeg(ch,2,ang);
    Serial.println(F("OK S")); return;
  }

  if (up.startsWith("ZERO ")){        // ZERO idx val
    int sp1 = cmd.indexOf(' '), sp2 = cmd.indexOf(' ', sp1+1);
    int idx = cmd.substring(sp1+1, sp2).toInt();
    float val = cmd.substring(sp2+1).toFloat();
    if (idx>=0 && idx<3) ZERO_DEG[idx] = val;
    Serial.println(F("OK ZERO")); return;
  }

  if (up.startsWith("DIR ")){         // DIR idx sgn
    int sp1 = cmd.indexOf(' '), sp2 = cmd.indexOf(' ', sp1+1);
    int idx = cmd.substring(sp1+1, sp2).toInt();
    int sgn = cmd.substring(sp2+1).toInt();
    if (idx>=0 && idx<3 && (sgn==1 || sgn==-1)) DIR[idx] = sgn;
    Serial.println(F("OK DIR")); return;
  }

  if (up.startsWith("XYZ ")){         // XYZ x y z
    float x,y,z;
    String args = cmd.substring(4);
    if (parse3Floats(args, x, y, z)) {
      setLegIK(x, y, z);
      Serial.println(F("OK XYZ"));
    } else {
      Serial.println(F("ERR XYZ"));
    }
    return;
  }

  Serial.println(F("ERR CMD"));
}

