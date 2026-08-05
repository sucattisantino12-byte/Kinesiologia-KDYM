# KDYM — Kinesiología y rehabilitación

App de **recepción y gestión** para centros de kinesiología. Pensada para el día a día:
recepción en tiempo real, agenda con calendario, fichas de pacientes y ejercicios.

## Funciones

- **Recepción en vivo**: boxes ocupados con temporizador, alarma (varios sonidos) cuando termina la sesión, sala de espera y estadísticas del día.
- **Poner al paciente directo en un box** → queda registrada la asistencia automáticamente.
- **Agenda con calendario mensual**: quién viene cada día; confirmar asistencia, reprogramar al próximo día disponible o dar el turno por perdido.
- **Días que viene** con **horario distinto por día** (ej: Lun 18:30, Mar 10:30) → genera los turnos automáticamente según las sesiones restantes.
- **Fichas de pacientes**: datos, obra social, diagnóstico, sesiones restantes, historial y **ejercicios por categoría** (catálogo propio o texto libre).
- **Alerta de últimas sesiones** (por renovar bono/autorización).
- **Aviso por WhatsApp** a la kinesióloga cuando termina una sesión (base para automatizar con un bot a futuro).

## Requisitos

- Python 3.10 o superior

## Cómo correrlo

```bash
pip install -r requirements.txt
python app.py
```

Después abrí **http://localhost:8090** en el navegador. Desde otro dispositivo en la
misma red WiFi: `http://IP-DE-LA-PC:8090`.

La base de datos (`kinesio.db`) se crea sola la primera vez, con algunos datos de
ejemplo que podés borrar desde la app.

## Aviso importante (datos de salud)

La app guarda datos médicos de pacientes. En Argentina eso cae bajo la **Ley 25.326 de
Protección de Datos Personales** (datos sensibles). Antes de usarla en producción con
pacientes reales, conviene contemplar consentimiento, acceso restringido y un hosting
adecuado. El archivo `kinesio.db` **no** se sube al repositorio (está en `.gitignore`).

## Stack

Flask + SQLite. Sin dependencias externas más allá de Flask.
