// =====================================================================
// Guía de uso por pestaña + recorrido guiado (tour).
// - "Guía de esta pestaña" (botón ? / tecla ?) abre un panel con pasos.
// - La primera vez que se entra a cada pestaña arranca un recorrido corto
//   que va señalando cada parte. Se puede repetir desde la guía.
// Los elementos señalados se marcan en los templates con data-tour="...".
// =====================================================================

const AYUDA = {
  recepcion: {
    titulo: 'Recepción',
    intro: 'La pantalla del día a día: quién llega, quién está en cada box y cuánto le falta a cada sesión. Se actualiza sola cada pocos segundos.',
    secciones: [
      { t: 'Cuando llega un paciente con turno', pasos: [
        'Buscalo en la <b>Sala del día</b> (a la derecha, ordenada por hora).',
        'Tocá <b>✓ Vino</b>. Si tiene obra social, podés cargar su <b>token</b> en ese momento. Se le descuenta una sesión y queda como <b>Presente</b>.',
        'Tocá <b>A un box →</b>, elegí el box y la duración, y empieza a correr el tiempo.',
      ] },
      { t: 'Cuando llega alguien sin turno', pasos: [
        'Tocá <b>Registrar llegada</b>.',
        'Escribí el nombre, apellido o DNI y tocá <b>Vino ✓</b> (ahí también podés cargar el token).',
        'La app le crea el turno de hoy a esta hora y lo deja presente.',
      ] },
      { t: 'Boxes y alarma', pasos: [
        'En un box libre tocá <b>Poner paciente</b> y elegí entre los que ya están presentes.',
        'Mientras dura la sesión ves la cuenta regresiva y una barra de progreso.',
        'Cuando termina, el box se pone <b>rojo</b>, suena la alarma y vibra el celular.',
        'Tocá <b>✓ Terminar</b> para liberarlo (ahí podés anotar los ejercicios de hoy) o <b>+ Tiempo</b> para extenderla.',
      ] },
      { t: 'Si un paciente no vino', pasos: [
        'Tocá la <b>✗</b> al lado de su nombre.',
        'Elegí: <b>reprogramar</b> a su próximo día disponible, <b>mover</b> a una fecha puntual o <b>dejar para después</b>.',
        'Si no se hace nada, pasados los minutos de tolerancia (Configuración) queda como <b>No vino</b> solo.',
      ] },
    ],
    tips: [
      'Tocá el nombre de cualquier paciente para ver su perfil rápido: sesiones, próximos turnos y ejercicios.',
      'Para que la alarma suene con el celular bloqueado, dejá la app abierta y tocá la pantalla una vez al empezar el día.',
      'Si marcaste “Vino” por error, usá el botón ↺ para deshacerlo.',
    ],
    tour: [
      { sel: '[data-tour="stats"]', t: 'El día de un vistazo', x: 'Turnos de hoy, quiénes vinieron, quién está en box y quién falta. Se actualiza solo.' },
      { sel: '[data-tour="llegada"]', t: 'Registrar llegada', x: 'Para pacientes que llegan sin turno: los buscás y los marcás como presentes en un toque.' },
      { sel: '[data-tour="boxes"]', t: 'Boxes', x: 'Cada box muestra si está libre o el tiempo que le queda a la sesión. Al terminar suena la alarma y el box se pone rojo.' },
      { sel: '[data-tour="sala"]', t: 'Sala del día', x: 'Los turnos de hoy por hora. Marcá ✓ Vino o ✗ No vino, y mandalos a un box.' },
      { sel: '[data-tour="sede"], [data-tour="sede-m"]', t: 'Sede', x: 'Estás trabajando en esta sede. Tocá acá para pasar a la otra.' },
      { sel: '[data-tour="buscar"], .mtop-ic[aria-label="Buscar"]', t: 'Búsqueda rápida', x: 'Encontrá cualquier paciente o acción desde cualquier pestaña. Atajo: Ctrl + K.' },
      { sel: '[data-tour="ayuda"], .mtop-ic[aria-label^="Guía"]', t: '¿Dudas?', x: 'Cada pestaña tiene su guía paso a paso. También podés repetir este recorrido cuando quieras.' },
    ],
  },

  agenda: {
    titulo: 'Agenda',
    intro: 'El calendario de turnos de cada sede. Desde acá das turnos, ves qué horarios quedan libres y reorganizás lo que haga falta.',
    secciones: [
      { t: 'Dar turnos a un paciente (plan de sesiones)', pasos: [
        'Tocá <b>Agregar turnos</b> y buscá el paciente (o cargalo nuevo). Adentro tenés el botón <b>Cómo funciona</b> con la explicación completa.',
        'En <b>Plan de sesiones</b> poné cuántas sesiones hace y desde qué fecha.',
        'Elegí <b>qué días viene</b> y el horario de cada día. El color te dice si hay lugar: <b>verde</b> libre, <b>amarillo</b> casi lleno, <b>rojo</b> lleno.',
        'Si es flexible, tocá <b>Ver los más libres</b>: la app te propone los horarios con más lugar.',
        'Tocá <b>Ver propuesta</b>, revisá las fechas (podés cambiar o quitar alguna) y confirmá.',
      ] },
      { t: 'Un turno suelto o un hueco libre', pasos: [
        'Tocá un día del calendario → <b>+ Dar turno</b>.',
        'O usá <b>Buscar hueco</b>: elegís el día y ves los horarios libres. Tocá uno y solo falta elegir el paciente.',
      ] },
      { t: 'Ver y reorganizar', pasos: [
        'Tocá un día para ver la lista de turnos a la derecha.',
        'Tocá un turno para <b>editar</b> fecha y hora, <b>reprogramarlo</b>, recordárselo por WhatsApp o darlo por perdido.',
        'Escribí un paciente en <b>Buscar</b> y sus días se resaltan en <b>violeta</b>.',
        'Usá <b>Filtrar días</b> para ver, por ejemplo, solo los martes y jueves.',
      ] },
      { t: 'Semáforo por horario', pasos: [
        'Elegí un horario en el <b>Semáforo</b> (por ejemplo 18:00).',
        'Cada día del calendario se pinta según cuánto lugar queda a esa hora.',
        'Ideal para responder rápido “¿tenés lugar los jueves a las 6?”.',
      ] },
      { t: 'Feriados', pasos: [
        'Tocá el día → <b>Marcar feriado</b>. Ese día no se pueden dar turnos.',
        'Si ya había turnos, la app te ofrece moverlos.',
        'También podés cargar todos los feriados nacionales desde Configuración.',
      ] },
    ],
    tips: [
      'Arriba elegís el calendario de cada sede sin tener que cambiar de sede.',
      'La vista <b>Semana</b> muestra los nombres de cada día, útil para imprimir o revisar.',
      'El tope de turnos por horario se configura en Configuración → Sedes.',
    ],
    tour: [
      { sel: '[data-tour="agregar-turnos"]', t: 'Agregar turnos', x: 'Lo más usado: armás el plan completo de un paciente (cantidad de sesiones, días y horarios) y lo confirmás de una.' },
      { sel: '[data-tour="hueco"]', t: 'Buscar hueco', x: 'Elegís un día y te muestra qué horarios quedan libres. Tocás uno y listo.' },
      { sel: '[data-tour="sede-cal"]', t: 'Calendario de cada sede', x: 'Cambiá entre Morón y Ramos para ver su agenda.' },
      { sel: '[data-tour="ag-buscar"]', t: 'Buscar un paciente', x: 'Escribí el nombre y sus días de turno se marcan en violeta en el calendario.' },
      { sel: '[data-tour="semaforo"]', t: 'Semáforo por horario', x: 'Elegí una hora y el calendario se pinta: verde hay lugar, amarillo falta uno, rojo lleno.' },
      { sel: '[data-tour="calendario"]', t: 'Calendario', x: 'El número azul es la cantidad de turnos. Tocá un día para dar un turno, verlo o marcar feriado.' },
      { sel: '[data-tour="dia"]', t: 'Día seleccionado', x: 'Acá aparece la lista de turnos del día elegido, con sus acciones.' },
    ],
  },

  pacientes: {
    titulo: 'Pacientes',
    intro: 'Todos los pacientes del centro. Los que tienen turno hoy aparecen primero. Tocá cualquiera para abrir su ficha.',
    secciones: [
      { t: 'Cargar un paciente nuevo', pasos: [
        'Tocá <b>+ Nuevo paciente</b>.',
        'Completá nombre y apellido (lo demás es opcional, pero el teléfono sirve para WhatsApp).',
        'Al guardar se abre <b>Agregar turnos</b> para darle sus días y horarios en el momento.',
      ] },
      { t: 'Encontrar un paciente', pasos: [
        'Escribí nombre, apellido, DNI u obra social en el buscador.',
        'Filtrá por <b>sede</b> para ver solo los que se atienden en Morón o en Ramos.',
        'Cambiá entre vista de <b>tarjetas</b> o <b>lista</b> según te resulte más cómodo.',
      ] },
      { t: 'Qué significan los colores', pasos: [
        'La barra muestra cuánto avanzó el tratamiento y abajo cuántas sesiones le quedan.',
        '<b>Amarillo</b>: le queda 1 sesión. <b>Rojo</b>: ya no le quedan.',
        'La etiqueta verde <b>Hoy</b> indica que tiene turno hoy.',
      ] },
    ],
    tips: [
      'Los nombres se guardan prolijos solos: “juan perez” queda “Juan Perez”.',
      'Desde cualquier pestaña podés buscar un paciente con Ctrl + K.',
    ],
    tour: [
      { sel: '[data-tour="nuevo-paciente"]', t: 'Nuevo paciente', x: 'Cargás los datos y enseguida le das los turnos.' },
      { sel: '[data-tour="pac-buscar"]', t: 'Buscador', x: 'Por nombre, apellido, DNI u obra social. Filtra mientras escribís.' },
      { sel: '[data-tour="pac-sede"]', t: 'Filtro por sede', x: 'Mostrá solo los pacientes que se atienden en una sede.' },
      { sel: '[data-tour="pac-vista"]', t: 'Tarjetas o lista', x: 'Elegí cómo ver la lista. La app lo recuerda.' },
      { sel: '#lista .pac-card', t: 'Cada paciente', x: 'Obra social, diagnóstico y sesiones restantes. Tocalo para abrir la ficha completa.' },
    ],
  },

  ficha: {
    titulo: 'Ficha del paciente',
    intro: 'Toda la información del paciente en un lugar: datos, turnos, ejercicios, evolución, pagos, estudios y consentimiento.',
    secciones: [
      { t: 'Turnos', pasos: [
        '<b>+ Agregar turnos</b> le da más sesiones (plan nuevo o extender el que tiene).',
        '<b>Cambiar días y horarios</b> mueve los turnos que le faltan a otros días/horas. Las sesiones ya hechas no se tocan.',
        'En <b>Historial de turnos</b> ves cada sesión con su estado (Vino, No vino, Sin registrar, Agendado). Tocá una para ver los ejercicios de ese día.',
      ] },
      { t: 'Seguimiento clínico', pasos: [
        '<b>Ejercicios</b>: elegí del catálogo o escribí uno nuevo, con series, repeticiones y peso.',
        '<b>Evolución</b>: anotá cómo va el paciente sesión a sesión.',
        '<b>Archivos y fotos</b>: subí estudios, recetas u órdenes (desde el celular podés sacar la foto directo).',
        '<b>Consentimiento</b>: el paciente firma con el dedo en la pantalla.',
      ] },
      { t: 'Tokens de la obra social', pasos: [
        'Al marcar <b>✓ Vino</b> en Recepción, si el paciente tiene obra social aparece un casillero para el <b>token</b>. Es opcional.',
        'En la ficha, la sección <b>Tokens de la obra social</b> muestra cada número con su fecha y sesión. Tocá el lápiz para <b>corregirlo</b> o borrarlo.',
        '<b>+ Agregar token</b> carga uno suelto: elegís la sesión y la fecha se completa sola.',
        '<b>Cargar varios</b> abre todas las sesiones con un casillero cada una. Si tenés los códigos juntos, pegalos (uno por renglón) y tocá <b>Repartir en orden</b>.',
        'Arriba te avisa cuántas sesiones que vino no tienen token, para completarlas antes de facturar.',
      ] },
      { t: 'Pagos', pasos: [
        'Cargá el <b>precio por sesión</b> y tocá Guardar.',
        'Con <b>+ Registrar pago</b> anotás lo que abona (podés elegir un precio guardado).',
        'El <b>saldo</b> se calcula solo: sesiones hechas × precio − pagado.',
      ] },
    ],
    tips: [
      'Si le renuevan la orden, entrá a <b>Editar datos</b> y subí las sesiones totales: la alerta de “por renovar” se reinicia.',
      'Eliminar un paciente borra también sus turnos, pagos y archivos. No se puede deshacer.',
    ],
    tour: [
      { sel: '[data-tour="ficha-head"]', t: 'Resumen', x: 'Sesiones hechas y restantes, con la barra de progreso del tratamiento.' },
      { sel: '[data-tour="ficha-acciones"]', t: 'Acciones rápidas', x: 'Agregar turnos, cambiar días y horarios, escribirle por WhatsApp o editar sus datos.' },
      { sel: '[data-tour="ficha-datos"]', t: 'Datos', x: 'DNI, teléfono, obra social, días y horarios, diagnóstico y notas.' },
      { sel: '[data-tour="ficha-historial"]', t: 'Historial de turnos', x: 'Todas sus sesiones con su estado. Tocá una para ver qué ejercicios hizo.' },
      { sel: '[data-tour="ficha-tokens"]', t: 'Tokens de la obra social', x: 'Cada token con su fecha y sesión. Podés corregirlos, agregar uno o cargar los de todas las sesiones de una.' },
      { sel: '[data-tour="ficha-pagos"]', t: 'Pagos y bono', x: 'Precio por sesión, lo pagado y el saldo pendiente.' },
    ],
  },

  ejercicios: {
    titulo: 'Biblioteca de ejercicios',
    intro: 'El catálogo de ejercicios del centro, ordenado por categoría. Lo que cargues acá aparece para elegir rápido en la ficha y al terminar un box.',
    secciones: [
      { t: 'Sumar un ejercicio', pasos: [
        'Tocá <b>+ Nuevo ejercicio</b>.',
        'Escribí el nombre y elegí una categoría (o escribí una nueva).',
        'Queda disponible enseguida para todos los pacientes.',
      ] },
      { t: 'Encontrar y ordenar', pasos: [
        'Usá el buscador o tocá una <b>categoría</b> para filtrar.',
        'Para quitar uno del catálogo tocá la <b>✕</b> (no se borra de los pacientes que ya lo tienen).',
      ] },
    ],
    tips: ['Al terminar una sesión en Recepción se abre “Ejercicios de hoy” con este mismo catálogo.'],
    tour: [
      { sel: '[data-tour="nuevo-ejercicio"]', t: 'Nuevo ejercicio', x: 'Sumá ejercicios al catálogo con su categoría.' },
      { sel: '[data-tour="ej-filtros"]', t: 'Buscar y filtrar', x: 'Escribí o tocá una categoría para encontrar rápido.' },
      { sel: '[data-tour="ej-lista"]', t: 'Catálogo', x: 'Agrupado por categoría. Estos son los que aparecen al asignar ejercicios.' },
    ],
  },

  plantillas: {
    titulo: 'Plantillas ortopédicas',
    intro: 'El seguimiento de los pedidos de plantillas: desde que se toma el molde hasta que el paciente las retira.',
    secciones: [
      { t: 'Cargar un pedido', pasos: [
        'Tocá <b>+ Nueva plantilla</b>.',
        'Elegí el paciente (o escribí nombre y teléfono si no está cargado). El teléfono es obligatorio para poder avisarle.',
        'Completá sede, fecha de molde, entrega estimada, precio y seña.',
      ] },
      { t: 'Seguir el estado', pasos: [
        'Cada pedido pasa por <b>Pedida → En fabricación → Lista → Entregada</b>.',
        'En <b>En curso</b> ves todos los que todavía no se entregaron. Al marcar uno como <b>Entregada</b> pasa a su pestaña, así la lista queda ordenada.',
        'Tocá la etapa en la barra de la tarjeta para cambiar el estado.',
        'Cuando está <b>Lista</b>, tocá <b>Avisar que está lista</b>: el WhatsApp sale armado con horario y dirección de retiro.',
      ] },
    ],
    tips: ['El horario y la dirección de retiro del mensaje se cargan en Configuración → Retiro de plantillas.'],
    tour: [
      { sel: '[data-tour="nueva-plantilla"]', t: 'Nuevo pedido', x: 'Cargá el pedido con paciente, fechas, precio y seña.' },
      { sel: '[data-tour="pl-filtros"]', t: 'Filtros por estado', x: '“En curso” muestra lo que falta entregar. Las entregadas quedan aparte, en su pestaña.' },
      { sel: '#pl-lista .pl-card, [data-tour="pl-lista"]', t: 'Cada pedido', x: 'Cambiá el estado y, cuando está lista, avisale al paciente por WhatsApp.' },
    ],
  },

  reportes: {
    titulo: 'Reportes',
    intro: 'Cómo viene el mes: asistencia, cantidad de turnos, ingresos, obras sociales y lo que falta cobrar.',
    secciones: [
      { t: 'Leer los números', pasos: [
        '<b>Asistencia</b>: de los turnos que ya pasaron, qué porcentaje vino.',
        '<b>Ingresos</b>: la suma de los pagos registrados en el mes.',
        'El gráfico muestra los <b>turnos de cada día</b>: azul vinieron, rojo no vinieron, gris por venir y rayado los que quedaron sin marcar.',
      ] },
      { t: 'Filtrar', pasos: [
        'Cambiá el <b>mes</b> arriba a la derecha para ver meses anteriores.',
        'Elegí una <b>sede</b> o mirá las dos juntas.',
      ] },
      { t: 'Cobros pendientes', pasos: [
        'Muestra cuánto se debe por obra social.',
        'Se calcula con el precio por sesión de cada paciente (se carga en su ficha) menos lo que ya pagó.',
      ] },
    ],
    tips: ['Para que los ingresos y cobros sean exactos, registrá cada pago desde la ficha del paciente.'],
    tour: [
      { sel: '[data-tour="rep-filtros"]', t: 'Mes y sede', x: 'Elegí qué mes y qué sede querés analizar.' },
      { sel: '[data-tour="rep-stats"]', t: 'Resumen del mes', x: 'Asistencia, turnos, ingresos y ausencias.' },
      { sel: '[data-tour="rep-dias"]', t: 'Turnos por día', x: 'Cada barra es un día del mes. Pasá el mouse o tocá para ver el detalle.' },
      { sel: '[data-tour="rep-os"]', t: 'Obras sociales', x: 'Qué obras sociales traen más turnos este mes.' },
    ],
  },

  notificaciones: {
    titulo: 'Notificaciones',
    intro: 'Los avisos importantes: pacientes a los que les quedan pocas sesiones y hay que renovarles la orden o el bono.',
    secciones: [
      { t: 'Cómo funciona', pasos: [
        'Cuando a un paciente le quedan <b>2 sesiones o menos</b>, aparece acá y en el contador rojo del menú.',
        'Tocá su nombre para ir a la ficha y renovarle las sesiones.',
        'Si ya lo resolviste, cerrá el aviso con la <b>✕</b>.',
      ] },
    ],
    tips: ['Si le cargás más sesiones al paciente, el aviso vuelve a activarse la próxima vez que le queden pocas.'],
    tour: [
      { sel: '[data-tour="notif-lista"]', t: 'Pacientes por renovar', x: 'Les quedan pocas sesiones. Entrá a la ficha para renovar o cerrá el aviso.' },
    ],
  },

  agturnos: {
    modal: true,
    titulo: 'Agregar turnos',
    intro: 'Desde acá le das los turnos a un paciente. Lo más común es armar el plan completo de una vez: cuántas sesiones, qué días y a qué hora.',
    secciones: [
      { t: 'El caso más común: un paciente que empieza', pasos: [
        'Elegí el <b>paciente</b> (o tocá “Cargar paciente nuevo”).',
        'Dejá marcado <b>Plan de sesiones</b> y <b>Nuevo plan</b>.',
        'Poné la <b>cantidad de sesiones</b> (ej: 10) y desde qué fecha puede empezar.',
        'En <b>¿Qué días viene?</b> tocá los días (ej: martes y jueves).',
        'En cada día se abre la lista de horarios: tocá la hora. <b>Verde</b> hay lugar, <b>amarillo</b> queda un lugar, <b>rojo</b> está lleno y no se puede elegir.',
        'Tocá <b>Ver propuesta de turnos</b>: aparecen todas las fechas. Podés cambiar la hora de alguna o quitarla con la ✕.',
        'Tocá <b>Confirmar y agendar</b>. Recién ahí se guardan.',
      ] },
      { t: 'Si el paciente es flexible con los horarios', pasos: [
        'En <b>¿Cómo elegir los horarios?</b> tocá <b>Ver los más libres</b>.',
        'La app muestra, para cada día de la semana, los horarios con más lugar.',
        'Elegí la hora en el desplegable y tocá <b>✓</b> en los días que el paciente acepte.',
        'Seguí con <b>Ver propuesta</b> y <b>Confirmar</b>, igual que siempre.',
      ] },
      { t: 'Si ya viene y le renovaron sesiones', pasos: [
        'Primero actualizá sus <b>sesiones totales</b> en la ficha (Editar datos).',
        'Abrí Agregar turnos y elegí <b>Extender (faltantes)</b>.',
        'La app calcula sola cuántos turnos faltan: solo elegí días y horarios y confirmá.',
      ] },
      { t: 'Si quiere cambiar de días u horario', pasos: [
        'Elegí <b>Cambiar días/horarios</b> (también está en la ficha).',
        'Marcá los días y horarios nuevos y desde qué fecha rigen.',
        'Al confirmar, sus turnos pendientes se mueven. Las sesiones que ya hizo quedan igual.',
      ] },
      { t: 'Turnos sueltos (Manual)', pasos: [
        'Tocá la pestaña <b>Manual (fechas sueltas)</b>.',
        'Elegí fecha y hora de cada turno. Con <b>+ Agregar otra fecha</b> sumás más.',
        '¿No sabés qué ofrecerle? Abrí <b>Ver próximos horarios libres</b> y tocá uno.',
      ] },
    ],
    tips: [
      'Los horarios son en punto o y media, y cada turno dura 30 minutos.',
      'Si cae un feriado, la propuesta lo avisa y lo pasa a la fecha siguiente.',
      'Si mientras armabas otro turno se llenó un horario, al confirmar te avisa en rojo y no guarda ese.',
    ],
    tour: [
      { sel: '#modal-agturnos .at-guia', t: 'La guía rápida', x: 'Un resumen de los 4 pasos. Abrila cuando tengas dudas: la dejamos arriba de todo.' },
      { sel: '#at-sede-field', t: 'Sede', x: 'Dónde van a ser los turnos. Viene puesta la sede en la que estás trabajando.' },
      { sel: '#at-buscar-wrap', t: 'Paciente', x: 'Escribí nombre, apellido o DNI y tocalo en la lista. Si todavía no está cargado, tocá “Cargar paciente nuevo”.' },
      { sel: '#at-tabs-field', t: 'Plan completo o turnos sueltos', x: '“Plan de sesiones” arma todos los turnos juntos (lo más común). “Manual” es para fechas sueltas, una por una.' },
      { sel: '#at-plan-modo', t: '¿Qué querés hacer?', x: 'Nuevo plan: turnos desde cero. Extender: agrega los que le faltan. Cambiar días/horarios: mueve los pendientes a otros días u horas.' },
      { sel: '#at-cant-desde', t: 'Cuántas y desde cuándo', x: 'La cantidad de sesiones y la primera fecha posible. Si el paciente ya tiene turnos, la fecha arranca después del último.' },
      { sel: '#at-estrategia-field', t: 'Cómo elegir los horarios', x: '“Elijo yo” cuando el paciente ya sabe qué días puede. “Ver los más libres” cuando es flexible: la app te muestra dónde hay más lugar.' },
      { sel: '#at-dias-field', t: 'Días que viene', x: 'Tocá los días. En cada uno se abre la lista de horarios con colores: verde libre, amarillo queda uno, rojo lleno.' },
      { sel: '#at-recom-wrap', t: 'Horarios más libres', x: 'Elegí la hora en cada día y tocá ✓ en los que el paciente acepte.' },
      { sel: '#at-prop-field', t: 'Revisar antes de guardar', x: 'Te muestra todas las fechas que se van a crear. Podés cambiar una hora o quitar un día. Todavía no se guardó nada.' },
      { sel: '#at-confirmar', t: 'Confirmar', x: 'Recién acá se guardan los turnos. Después los ves en la Agenda y en la ficha del paciente.' },
    ],
  },

  paciente: {
    modal: true,
    titulo: 'Cargar un paciente nuevo',
    intro: 'Con nombre y apellido alcanza para empezar. Al guardar se abre Agregar turnos para darle sus días y horarios en el mismo paso.',
    secciones: [
      { t: 'Qué completar', pasos: [
        '<b>Nombre y apellido</b> (obligatorios). Se guardan prolijos aunque los escribas en minúscula.',
        '<b>DNI</b>: si ya existe alguien con ese DNI o ese nombre, la app te avisa para no duplicarlo.',
        '<b>Celular</b>: se usa para mandarle recordatorios y avisos por WhatsApp. Podés escribirlo como quieras (11 5678-9012).',
        '<b>Obra social</b>: elegila de la lista o escribí otra. Si paga él, poné “Particular”.',
        '<b>Diagnóstico</b>: la lesión o motivo. Se ve en la sala del día y en la ficha.',
      ] },
      { t: 'Sesiones', pasos: [
        '<b>Sesiones totales</b>: las que autorizó la obra social o compró (ej: 10).',
        '<b>Sesiones ya hechas</b>: solo si venía atendiéndose antes de usar la app. Si es nuevo, dejá 0.',
        'Cada vez que marcás “Vino” se descuenta una. Cuando le quedan 2, aparece en Notificaciones.',
      ] },
      { t: 'Después de guardar', pasos: [
        'Se abre <b>Agregar turnos</b> con el paciente ya elegido.',
        'Si preferís darle los turnos más tarde, cerrá esa ventana: el paciente queda guardado igual.',
      ] },
    ],
    tips: ['Todo lo que no cargues ahora lo podés completar después desde la ficha, con “Editar datos”.'],
    tour: [
      { sel: '#np-fila-nombre', t: 'Nombre y apellido', x: 'Son los únicos datos obligatorios. Se guardan prolijos aunque los escribas en minúscula.' },
      { sel: '#np-fila-contacto', t: 'DNI y celular', x: 'El DNI evita cargar dos veces a la misma persona. El celular se usa para recordatorios por WhatsApp.' },
      { sel: '#np-fila-obra', t: 'Obra social', x: 'Elegila de la lista o escribí otra. Si paga él, poné “Particular”.' },
      { sel: '#np-fila-sesiones', t: 'Sesiones', x: 'Totales: las que autorizó la obra social o compró. Ya hechas: solo si venía atendiéndose. Cuando le queden 2, la app avisa.' },
      { sel: '#np-guardar', t: 'Guardar y dar turnos', x: 'Guarda el paciente y abre Agregar turnos para darle sus días y horarios en el mismo paso.' },
    ],
  },

  configuracion: {
    titulo: 'Configuración',
    intro: 'Todo lo que se ajusta una vez: sedes, horarios del centro, precios, feriados, avisos y copias de seguridad.',
    secciones: [
      { t: 'Para arrancar (una sola vez)', pasos: [
        'En <b>Sedes</b> poné el <b>tope</b> de turnos por horario (normalmente, la cantidad de boxes).',
        'En <b>Horario del centro</b> marcá qué días abre y en qué horario.',
        'Tocá <b>Cargar feriados de Argentina</b>.',
        'Cargá los <b>precios</b> que usan y el horario y la dirección de <b>retiro de plantillas</b>.',
      ] },
      { t: 'En este dispositivo', pasos: [
        '<b>Modo oscuro</b> y <b>sonido de la alarma</b> se guardan solo en este celular o compu.',
        'Probá el sonido antes de elegirlo.',
      ] },
      { t: 'Datos', pasos: [
        'Descargá la <b>copia de seguridad</b> cada tanto y guardala en Drive o un pendrive.',
        'El <b>Modo demo</b> muestra botones para cargar datos de ejemplo y probar la alarma. Dejalo apagado en el uso diario.',
      ] },
    ],
    tips: ['Los cambios de sedes, horarios y precios valen para todos los que usan la app.'],
    tour: [
      { sel: '[data-tour="cfg-indice"]', t: 'Secciones', x: 'Saltá directo a lo que necesitás ajustar.' },
      { sel: '#cfg-sedes', t: 'Sedes y tope', x: 'Cuántos turnos se pueden dar en un mismo horario en cada sede.' },
      { sel: '#cfg-horario', t: 'Horario del centro', x: 'Los días y horarios en que se pueden dar turnos.' },
      { sel: '#cfg-datos', t: 'Copia de seguridad', x: 'Descargá todos los datos para tenerlos resguardados.' },
    ],
  },
};

// ---------------------------------------------------------------------
function _paginaAyuda() { return document.body.dataset.pagina || ''; }

// ---- Panel de la guía ----
function abrirAyuda(pagina) {
  const pg = pagina || _paginaAyuda();
  const g = AYUDA[pg];
  if (!g) { toast('Esta pantalla no tiene guía todavía'); return; }
  let bg = document.getElementById('ay-bg'), pn = document.getElementById('ay-panel');
  if (!pn) {
    bg = document.createElement('div'); bg.id = 'ay-bg'; bg.className = 'ay-bg';
    pn = document.createElement('aside'); pn.id = 'ay-panel'; pn.className = 'ay-panel';
    pn.setAttribute('role', 'dialog'); pn.setAttribute('aria-label', 'Guía de uso');
    document.body.appendChild(bg); document.body.appendChild(pn);
    bg.addEventListener('click', cerrarAyuda);
  }
  const otras = Object.keys(AYUDA).filter(k => k !== pg && k !== 'ficha' && !AYUDA[k].modal).map(k =>
    `<a href="/${k === 'ejercicios' ? 'ejercicios' : k}?ayuda=1">${_I.ayuda}${AYUDA[k].titulo}</a>`).join('');
  pn.innerHTML = `
    <div class="ay-head">
      <button class="x" onclick="cerrarAyuda()" aria-label="Cerrar">&times;</button>
      <div class="ay-kicker">${g.modal ? 'Tutorial' : 'Guía de uso'}</div>
      <h2>${g.titulo}</h2>
      <p>${g.intro}</p>
      <div class="ay-acciones">
        ${(g.tour || []).length ? `<button class="btn btn-sm btn-tour" onclick="cerrarAyuda(); setTimeout(() => iniciarTour('${pg}'), 250)">${_I.tour} Hacer el recorrido</button>` : ''}
        <button class="btn btn-sm btn-sec" onclick="cerrarAyuda(); abrirBuscador()">${_I.buscar} Buscar</button>
      </div>
    </div>
    <div class="ay-body">
      <div class="ay-h">Paso a paso</div>
      ${g.secciones.map((s, i) => `
        <details class="ay-sec" ${i === 0 ? 'open' : ''}>
          <summary><span class="ay-num">${i + 1}</span>${s.t}</summary>
          <ol class="ay-pasos">${s.pasos.map(p => `<li>${p}</li>`).join('')}</ol>
        </details>`).join('')}
      ${(g.tips || []).length ? `<div class="ay-tips"><h4>💡 Consejos</h4><ul>${g.tips.map(t => `<li>${t}</li>`).join('')}</ul></div>` : ''}
      <div class="ay-h" style="margin-top:22px;">Atajos</div>
      <div class="ay-sec" style="padding:12px 14px; font-size:13.5px; color:var(--texto2); line-height:1.9;">
        <div><kbd class="kbd-claro">Ctrl</kbd> + <kbd class="kbd-claro">K</kbd> buscar pacientes y acciones</div>
        <div><kbd class="kbd-claro">?</kbd> abrir esta guía · <kbd class="kbd-claro">Esc</kbd> cerrar ventanas</div>
      </div>
      <div class="ay-h" style="margin-top:22px;">Otras guías</div>
      <div class="ay-otras">${otras}</div>
    </div>`;
  requestAnimationFrame(() => { bg.classList.add('show'); pn.classList.add('show'); });
  const esc = (e) => { if (e.key === 'Escape') { e.preventDefault(); cerrarAyuda(); document.removeEventListener('keydown', esc, true); } };
  document.addEventListener('keydown', esc, true);
}
function cerrarAyuda() {
  const bg = document.getElementById('ay-bg'), pn = document.getElementById('ay-panel');
  if (bg) bg.classList.remove('show');
  if (pn) pn.classList.remove('show');
}

// ---- Recorrido guiado ----
let _TOUR = null;

function _visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return false;
  const cs = getComputedStyle(el);
  return cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity !== 0;
}
function _buscarVisible(sel) {
  for (const s of sel.split(',')) {
    const els = document.querySelectorAll(s.trim());
    for (const el of els) if (_visible(el)) return el;
  }
  return null;
}

function iniciarTour(pagina, conBienvenida) {
  const pg = pagina || _paginaAyuda();
  const g = AYUDA[pg];
  if (!g || !(g.tour || []).length) return;
  // Sólo los pasos cuyo elemento existe y se ve (en celular algunos no están).
  const pasos = g.tour.filter(p => _buscarVisible(p.sel));
  if (conBienvenida) pasos.unshift({ hola: true });
  if (!pasos.length) return;
  terminarTour(false);
  cerrarAyuda();
  if (!g.modal) document.querySelectorAll('.modal-bg.show').forEach(m => m.classList.remove('show'));
  const capa = document.createElement('div');
  capa.className = 'tour-capa';
  capa.innerHTML = '<div class="tour-foco"></div><div class="tour-pop" role="dialog" aria-live="polite"></div>';
  document.body.appendChild(capa);
  _TOUR = { pg, pasos, i: 0, capa, foco: capa.querySelector('.tour-foco'), pop: capa.querySelector('.tour-pop') };
  capa.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tour-accion]');
    if (!b) return;
    const a = b.dataset.tourAccion;
    if (a === 'sig') _tourIr(_TOUR.i + 1);
    else if (a === 'ant') _tourIr(_TOUR.i - 1);
    else terminarTour(true);
  });
  document.addEventListener('keydown', _tourTeclas, true);
  window.addEventListener('resize', _tourReubicar);
  window.addEventListener('scroll', _tourReubicar, true);
  _tourIr(0);
}

function _tourTeclas(e) {
  if (!_TOUR) return;
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); terminarTour(true); }
  else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); _tourIr(_TOUR.i + 1); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); _tourIr(_TOUR.i - 1); }
}

function _tourIr(i) {
  const T = _TOUR;
  if (!T) return;
  if (i >= T.pasos.length) {
    const modal = AYUDA[T.pg] && AYUDA[T.pg].modal;
    terminarTour(true);
    toast(modal ? '¡Listo! Si te olvidás algo, tocá “Cómo funciona” arriba.' : '¡Listo! Si te olvidás algo, tocá “Guía de uso”.', 'ok');
    return;
  }
  if (i < 0) return;
  T.i = i;
  const p = T.pasos[i];
  const total = T.pasos.length;
  // Los puntitos cuentan sólo los pasos reales (no la bienvenida).
  const off = T.pasos[0].hola ? 1 : 0;
  const dots = p.hola ? '' : T.pasos.slice(off).map((_, k) => `<i class="${k + off === i ? 'on' : ''}"></i>`).join('');
  const ultimo = i === total - 1;
  const nav = `<div class="tour-nav">
      <div class="tour-dots">${dots}</div>
      ${i > 0 ? '<button class="btn btn-ghost btn-sm" data-tour-accion="ant">Anterior</button>' : '<button class="tour-saltar" data-tour-accion="fin">Ahora no</button>'}
      <button class="btn btn-primary btn-sm" data-tour-accion="sig">${ultimo ? 'Listo' : (p.hola ? 'Empezar' : 'Siguiente')}</button>
    </div>`;
  if (p.hola) {
    const g = AYUDA[T.pg];
    T.pop.innerHTML = `<div class="tour-hola">
        <div class="tour-logo">${document.querySelector('.side-logo .mk svg, .mtop-mk svg') ? document.querySelector('.side-logo .mk svg, .mtop-mk svg').outerHTML : ''}</div>
        <div class="tour-paso">Recorrido rápido · ${total - 1} pasos</div>
        <h4>${g.titulo}</h4>
        <p>${g.intro}</p>
      </div>${nav}`;
    T.el = null;
  } else {
    T.el = _buscarVisible(p.sel);
    T.pop.innerHTML = `<div class="tour-paso">Paso ${i - off + 1} de ${total - off}</div><h4>${p.t}</h4><p>${p.x}</p>${nav}`;
    if (T.el) {
      const r = T.el.getBoundingClientRect();
      const fuera = r.top < 70 || r.bottom > window.innerHeight - 90;
      if (fuera) T.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
  T.pop.classList.remove('entra'); void T.pop.offsetWidth; T.pop.classList.add('entra');
  _tourReubicar();
  setTimeout(_tourReubicar, 380);
  const b = T.pop.querySelector('[data-tour-accion="sig"]');
  if (b) setTimeout(() => b.focus({ preventScroll: true }), 50);
}

function _tourReubicar() {
  const T = _TOUR;
  if (!T) return;
  const vw = window.innerWidth, vh = window.innerHeight;
  const pw = T.pop.offsetWidth, ph = T.pop.offsetHeight;
  if (!T.el) {
    T.foco.classList.add('centro');
    T.pop.style.left = Math.round((vw - pw) / 2) + 'px';
    T.pop.style.top = Math.round((vh - ph) / 2) + 'px';
    return;
  }
  T.foco.classList.remove('centro');
  const r = T.el.getBoundingClientRect();
  const pad = 6;
  // Si el elemento es más alto que la pantalla, se enfoca sólo la parte visible.
  const top = Math.max(r.top - pad, 8), bottom = Math.min(r.bottom + pad, vh - 8);
  Object.assign(T.foco.style, {
    left: (r.left - pad) + 'px', top: top + 'px',
    width: (r.width + pad * 2) + 'px', height: Math.max(bottom - top, 20) + 'px',
  });
  const gap = 14;
  let x, y;
  const abajo = vh - bottom, arriba = top, der = vw - r.right, izq = r.left;
  if (abajo >= ph + gap) { y = bottom + gap; x = r.left + r.width / 2 - pw / 2; }
  else if (arriba >= ph + gap) { y = top - ph - gap; x = r.left + r.width / 2 - pw / 2; }
  else if (der >= pw + gap) { x = r.right + pad + gap; y = r.top + r.height / 2 - ph / 2; }
  else if (izq >= pw + gap) { x = r.left - pad - gap - pw; y = r.top + r.height / 2 - ph / 2; }
  else { x = (vw - pw) / 2; y = vh - ph - 16; }
  x = Math.min(Math.max(12, x), vw - pw - 12);
  y = Math.min(Math.max(12, y), vh - ph - 12);
  T.pop.style.left = Math.round(x) + 'px';
  T.pop.style.top = Math.round(y) + 'px';
}

function terminarTour(marcarVisto) {
  if (!_TOUR) return;
  if (marcarVisto) { try { localStorage.setItem('kdym_tour_' + _TOUR.pg, '1'); } catch (e) {} }
  _TOUR.capa.remove();
  _TOUR = null;
  document.removeEventListener('keydown', _tourTeclas, true);
  window.removeEventListener('resize', _tourReubicar);
  window.removeEventListener('scroll', _tourReubicar, true);
}

// Recorrido automático la primera vez que se abre una ventana con tutorial
// (Agregar turnos, Nuevo paciente). Devuelve true si arrancó.
function tourModalPrimeraVez(clave) {
  let visto = false;
  try { visto = localStorage.getItem('kdym_tour_' + clave) === '1'; } catch (e) {}
  if (visto || _TOUR || document.querySelector('.tour-capa')) return false;
  setTimeout(() => { if (!_TOUR) iniciarTour(clave, true); }, 380);
  return true;
}

// ---- Botón "Cómo se usa" en el encabezado de cada pestaña ----
(function () {
  const pg = _paginaAyuda();
  if (!AYUDA[pg]) return;
  const head = document.querySelector('.page-head');
  if (!head) return;
  let acc = head.querySelector('.page-head-actions');
  if (!acc) { acc = document.createElement('div'); acc.className = 'page-head-actions'; head.appendChild(acc); }
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'btn btn-ghost btn-ayuda';
  b.title = 'Guía de esta pestaña (tecla ?)';
  b.innerHTML = _I.ayuda + '<span>Cómo se usa</span>';
  b.addEventListener('click', () => abrirAyuda(pg));
  acc.prepend(b);
})();

// ---- Arranque automático ----
(function () {
  const pg = _paginaAyuda();
  if (!AYUDA[pg]) return;
  const params = new URLSearchParams(location.search);
  if (params.get('ayuda') === '1') {
    params.delete('ayuda');
    history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : '') + location.hash);
    window.addEventListener('load', () => setTimeout(() => abrirAyuda(pg), 500));
    return;
  }
  const forzar = params.get('tour') === '1';
  let visto = false;
  try { visto = localStorage.getItem('kdym_tour_' + pg) === '1'; } catch (e) {}
  if ((visto && !forzar) || params.get('accion')) return;

  function cuandoListo(fn) {
    const splash = document.getElementById('splash');
    if (splash && splash.classList.contains('on')) {
      const obs = new MutationObserver(() => { if (!document.getElementById('splash')) { obs.disconnect(); fn(); } });
      obs.observe(document.body, { childList: true });
    } else fn();
  }
  window.addEventListener('load', () => cuandoListo(() => setTimeout(() => {
    // No interrumpir si ya hay una ventana abierta.
    if (document.querySelector('.modal-bg.show, .cmdk-bg.show, .ay-panel.show')) return;
    iniciarTour(pg, true);
  }, 1300)));
})();
