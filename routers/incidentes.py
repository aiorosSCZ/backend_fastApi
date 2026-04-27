from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form
from sqlalchemy.orm import Session
import crud, schemas, models
from database import get_db
from services.ai_service import AIService
import os
import uuid

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/", response_model=schemas.IncidenteResponse)
def create_incidente(incidente: schemas.IncidenteCreate, db: Session = Depends(get_db)):
    return crud.create_incidente(db=db, incidente=incidente)

@router.get("/{id_incidente}", response_model=schemas.IncidenteResponse)
def read_incidente(id_incidente: int, db: Session = Depends(get_db)):
    db_incidente = db.query(models.Incidente).filter(models.Incidente.id_incidente == id_incidente).first()
    if not db_incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    return db_incidente

@router.get("/{id_incidente}/tracking")
def get_incidente_tracking(id_incidente: int, db: Session = Depends(get_db)):
    import models
    incidente = db.query(models.Incidente).filter(models.Incidente.id_incidente == id_incidente).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
        
    asistencia = db.query(models.Asistencia).filter(models.Asistencia.id_incidente == id_incidente).first()
    
    lat_tec, lng_tec = None, None
    if asistencia and asistencia.tecnico:
        lat_tec = asistencia.tecnico.ubicacion_actual_latitud
        lng_tec = asistencia.tecnico.ubicacion_actual_longitud
        
    return {
        "estado": incidente.estado_solicitud,
        "lat_cliente": incidente.ubicacion_latitud,
        "lng_cliente": incidente.ubicacion_longitud,
        "lat_tecnico": lat_tec or -17.7780,
        "lng_tecnico": lng_tec or -63.1750
    }

# Eliminado endpoint duplicado /aceptar

@router.post("/reportar")
async def reportar_incidente(
    id_cliente: int = Form(...),
    id_vehiculo: int = Form(...),
    ubicacion_latitud: float = Form(...),
    ubicacion_longitud: float = Form(...),
    descripcion_manual: str = Form(""),
    audio: UploadFile = File(None),
    foto: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    # Guardar archivos si existen
    audio_path = None
    foto_path = None
    
    if audio:
        ext = os.path.splitext(audio.filename)[1]
        audio_name = f"audio_{uuid.uuid4()}{ext}"
        audio_path = os.path.join(UPLOAD_DIR, audio_name)
        with open(audio_path, "wb") as buffer:
            buffer.write(await audio.read())
            
    if foto:
        ext = os.path.splitext(foto.filename)[1]
        foto_name = f"foto_{uuid.uuid4()}{ext}"
        foto_path = os.path.join(UPLOAD_DIR, foto_name)
        with open(foto_path, "wb") as buffer:
            buffer.write(await foto.read())

    # Crear el incidente en BD
    # Nota: Como models.Incidente podría no tener aún campos para las rutas de archivos en models.py,
    # los guardamos en la descripción o simplemente devolvemos éxito para la Fase 1.
    # Vamos a crear el registro usando el crud básico
    incidente_data = schemas.IncidenteCreate(
        id_cliente=id_cliente,
        id_vehiculo=id_vehiculo,
        ubicacion_latitud=ubicacion_latitud,
        ubicacion_longitud=ubicacion_longitud,
        descripcion_manual=descripcion_manual,
        tipo_problema="Buscando..."
    )
    db_incidente = crud.create_incidente(db=db, incidente=incidente_data)
    
    # Análisis Multimodal con IA (Gemini 1.5 Flash)
    ai_result = AIService.analizar_incidente(audio_path, foto_path, descripcion_manual)
    
    # Actualizar los datos del incidente con el veredicto de la IA
    db_incidente.tipo_problema = ai_result.get("categoria", "Otro")
    db_incidente.nivel_prioridad = ai_result.get("urgencia", "Media")
    db.commit()
    db.refresh(db_incidente)
    
    # Guardar el desglose detallado en AnalisisIA
    db_analisis = models.AnalisisIA(
        id_incidente=db_incidente.id_incidente,
        clasificacion_sugerida=ai_result.get("categoria", "Otro"),
        resumen_estructurado=ai_result.get("diagnostico_ia", "Sin diagnóstico disponible.")
    )
    db.add(db_analisis)
    db.commit()
    
    # Búsqueda Geoespacial de Talleres (Fase 3)
    from services.matching_service import buscar_talleres_cercanos
    talleres_cercanos = buscar_talleres_cercanos(
        db, 
        lat_cliente=ubicacion_latitud, 
        lon_cliente=ubicacion_longitud, 
        radio_km=10.0
    )
    
    # Escalado automático si no hay talleres en 10 km
    if not talleres_cercanos:
        talleres_cercanos = buscar_talleres_cercanos(
            db, 
            lat_cliente=ubicacion_latitud, 
            lon_cliente=ubicacion_longitud, 
            radio_km=20.0
        )
    
    # Notificaciones WebSocket en tiempo real
    from main import manager
    import asyncio
    
    for taller in talleres_cercanos:
        payload = {
            "type": "NUEVA_EMERGENCIA",
            "id_incidente": db_incidente.id_incidente,
            "problema": db_incidente.tipo_problema,
            "prioridad": db_incidente.nivel_prioridad,
            "distancia_km": taller["distancia_km"],
            "latitud": ubicacion_latitud,
            "longitud": ubicacion_longitud,
            "transcripcion_audio": db_incidente.transcripcion_audio,
            "url_audio_evidencia": db_incidente.url_audio_evidencia,
            "url_foto_evidencia": db_incidente.url_foto_evidencia,
            "evaluacion_ia": db_incidente.diagnostico_ia
        }
        asyncio.create_task(manager.send_personal_message(payload, taller["id_taller"]))

    return {
        "status": "success",
        "message": "Incidente reportado, analizado por IA y talleres asignados.",
        "id_incidente": db_incidente.id_incidente,
        "evaluacion_ia": ai_result,
        "talleres_notificados": talleres_cercanos
    }

@router.post("/{id_incidente}/aceptar")
def aceptar_incidente(id_incidente: int, payload: dict, db: Session = Depends(get_db)):
    import models
    incidente = db.query(models.Incidente).filter(models.Incidente.id_incidente == id_incidente).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
        
    id_taller = payload.get("id_taller")
    if not id_taller:
        raise HTTPException(status_code=400, detail="El ID del taller es requerido")
        
    id_tecnico = payload.get("id_tecnico")
    if id_tecnico:
        tecnico = db.query(models.Tecnico).filter(models.Tecnico.id_tecnico == id_tecnico).first()
    else:
        tecnico = db.query(models.Tecnico).filter(
            models.Tecnico.id_taller == id_taller,
            models.Tecnico.estado_operativo == 'Disponible'
        ).first()
        if not tecnico:
            tecnico = db.query(models.Tecnico).filter(models.Tecnico.id_taller == id_taller).first()
        
    if not tecnico:
        raise HTTPException(status_code=400, detail="Este taller no tiene técnicos registrados")
         
    incidente.estado_solicitud = 'Aceptado'
    
    # Verificar si ya existe asistencia
    existente = db.query(models.Asistencia).filter(models.Asistencia.id_incidente == id_incidente).first()
    if existente:
        return {"status": "success", "message": "El servicio ya fue tomado por este u otro taller."}

    asistencia = models.Asistencia(
        id_incidente=id_incidente,
        id_taller=id_taller,
        id_tecnico=tecnico.id_tecnico
    )
    db.add(asistencia)
    db.commit()
    
    # Enviar notificaciones Firebase
    try:
        from services.firebase_service import send_push_notification
        
        cliente = db.query(models.Cliente).filter(models.Cliente.id_cliente == incidente.id_cliente).first()
        if cliente and cliente.fcm_token:
            send_push_notification(
                fcm_token=cliente.fcm_token,
                titulo="¡Auxilio en camino!",
                mensaje="Tu solicitud ha sido aceptada. Un técnico se dirige a tu ubicación."
            )
            
        if tecnico and tecnico.fcm_token:
            send_push_notification(
                fcm_token=tecnico.fcm_token,
                titulo="Nuevo Servicio Asignado",
                mensaje="Se te ha asignado un nuevo incidente vehicular."
            )
    except Exception as e:
        print(f"Error disparando notificaciones push: {e}")

    return {"status": "success", "message": "Servicio tomado correctamente"}

@router.get("/", response_model=list[schemas.IncidenteResponse])
def read_incidentes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    incidentes = crud.get_incidentes(db, skip=skip, limit=limit)
    return incidentes

@router.post("/{id_incidente}/calificar", response_model=schemas.ValoracionResponse)
def calificar_incidente(id_incidente: int, request: schemas.ValoracionCreate, db: Session = Depends(get_db)):
    # 1. Buscar la asistencia
    db_asistencia = db.query(models.Asistencia).filter(models.Asistencia.id_incidente == id_incidente).first()
    if not db_asistencia:
        raise HTTPException(status_code=404, detail="Asistencia no encontrada para este incidente")
        
    # 2. Verificar si ya fue calificada
    db_valoracion = db.query(models.Valoracion).filter(models.Valoracion.id_asistencia == db_asistencia.id_asistencia).first()
    if db_valoracion:
        raise HTTPException(status_code=400, detail="Este servicio ya ha sido calificado")
        
    # 3. Crear la valoración
    nueva_valoracion = models.Valoracion(
        id_asistencia=db_asistencia.id_asistencia,
        puntuacion=request.puntuacion,
        comentario=request.comentario
    )
    db.add(nueva_valoracion)
    db.commit()
    db.refresh(nueva_valoracion)
    return nueva_valoracion

@router.post("/{id_incidente}/estado")
def actualizar_estado_incidente(id_incidente: int, payload: dict, db: Session = Depends(get_db)):
    import models
    incidente = db.query(models.Incidente).filter(models.Incidente.id_incidente == id_incidente).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
        
    nuevo_estado = payload.get("estado")
    if not nuevo_estado:
        raise HTTPException(status_code=400, detail="El estado es requerido")
        
    incidente.estado_solicitud = nuevo_estado
    db.commit()
    return {"status": "success", "message": f"Estado actualizado a {nuevo_estado}"}
