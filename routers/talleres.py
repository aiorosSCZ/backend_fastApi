from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import crud, schemas, schemas_auth, models
from database import get_db

router = APIRouter()

@router.post("/", response_model=schemas.TallerResponse)
def create_taller(taller: schemas.TallerCreate, db: Session = Depends(get_db)):
    # 1. Verificar si el correo ya existe
    existing_email = get_taller_by_email(db, taller.correo)
    if existing_email:
        raise HTTPException(
            status_code=400, 
            detail="Este correo electrónico ya está registrado en el sistema."
        )
    
    # 2. Verificar si el NIT ya existe
    existing_nit = db.query(models.Taller).filter(models.Taller.nit == taller.nit).first()
    if existing_nit:
        raise HTTPException(
            status_code=400, 
            detail=f"El NIT {taller.nit} ya se encuentra registrado. Si es un error, contacta a soporte."
        )

    return crud.create_taller(db=db, taller=taller)

@router.get("/{id_taller}", response_model=schemas.TallerResponse)
def read_taller(id_taller: int, db: Session = Depends(get_db)):
    taller = db.query(models.Taller).filter(models.Taller.id_taller == id_taller).first()
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")
    return taller

@router.get("/", response_model=list[schemas.TallerResponse])
def read_talleres(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    talleres = crud.get_talleres(db, skip=skip, limit=limit)
    return talleres

def get_taller_by_email(db: Session, email: str):
    return db.query(models.Taller).filter(models.Taller.correo == email).first()

@router.post("/login")
def login(request: schemas_auth.LoginRequest, db: Session = Depends(get_db)):
    correo_limpio = request.correo.strip().lower()
    clave_limpia = request.password.strip()

    # 0. Cortocircuito para SuperAdmin (Garantiza velocidad y cero bloqueos)
    if correo_limpio == "admin@asistauto.com" and clave_limpia == "admin123":
        return {
            "access_token": "fake-jwt-token-admin",
            "token_type": "bearer",
            "user_id": 1,
            "user_name": "SuperAdmin",
            "role": "admin"
        }

    # 1. Intentar como Taller
    db_taller = db.query(models.Taller).filter(models.Taller.correo == correo_limpio).first()
    if db_taller and crud.verify_password(request.password, db_taller.password_hash):
        return {
            "access_token": "fake-jwt-token-taller",
            "token_type": "bearer",
            "user_id": db_taller.id_taller,
            "user_name": db_taller.razon_social,
            "nit": db_taller.nit,
            "direccion": db_taller.direccion_fisica,
            "role": "taller"
        }
        
    # 2. Intentar como Admin
    
    # Crear admin por defecto si la tabla está vacía
    admins_count = db.query(models.Admin).count()
    if admins_count == 0:
        default_admin = models.Admin(
            nombre="SuperAdmin",
            correo="asiscar.asistente@gmail.com",
            password_hash=crud.pwd_context.hash("AsiscarAsistente2026")
        )
        db.add(default_admin)
        db.commit()
        
    db_admin = db.query(models.Admin).filter(models.Admin.correo == request.correo).first()
    if db_admin and crud.verify_password(request.password, db_admin.password_hash):
        return {
            "access_token": "fake-jwt-token-admin",
            "token_type": "bearer",
            "user_id": db_admin.id_admin,
            "user_name": db_admin.nombre,
            "role": "admin"
        }
        
    raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

from fastapi import UploadFile, File
import os
import shutil

@router.post("/{id_taller}/upload-docs")
async def upload_documentos(
    id_taller: int,
    foto_nit: UploadFile = File(None),
    foto_local: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    import models
    taller = db.query(models.Taller).filter(models.Taller.id_taller == id_taller).first()
    
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")

    # TODO: Integración real con Supabase Storage. 
    # Por ahora, simularemos que subimos y obtenemos las URLs.
    
    if foto_nit:
        # Simulamos que subimos a Supabase y nos da esta URL:
        fake_url_nit = f"https://supabase.co/storage/v1/object/public/documentos_verificacion/nit_{id_taller}.jpg"
        taller.foto_nit_url = fake_url_nit
        
    if foto_local:
        # Simulamos que subimos a Supabase y nos da esta URL:
        fake_url_local = f"https://supabase.co/storage/v1/object/public/documentos_verificacion/local_{id_taller}.jpg"
        taller.foto_local_url = fake_url_local

    if foto_nit or foto_local:
        db.commit()
        db.refresh(taller)

    return {"message": "Documentos subidos exitosamente", "foto_nit_url": taller.foto_nit_url, "foto_local_url": taller.foto_local_url}

@router.post("/{id_taller}/horario")
def update_horario(id_taller: int, payload: dict, db: Session = Depends(get_db)):
    import models
    from datetime import time
    taller = db.query(models.Taller).filter(models.Taller.id_taller == id_taller).first()
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")
        
    taller.es_24_7 = payload.get("es_24_7", False)
    
    ha = payload.get("horario_apertura")
    hc = payload.get("horario_cierre")
    
    try:
        if ha and ":" in ha:
            h, m = map(int, ha.split(":"))
            taller.horario_apertura = time(hour=h, minute=m)
        if hc and ":" in hc:
            h, m = map(int, hc.split(":"))
            taller.horario_cierre = time(hour=h, minute=m)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Formato de hora inválido (Use HH:MM)")
            
    db.commit()
    return {"status": "success", "message": "Horario actualizado correctamente"}

@router.patch("/{id_taller}/aprobar")
def aprobar_taller(id_taller: int, db: Session = Depends(get_db)):
    """
    Endpoint para que el Superadmin apruebe un taller.
    Cambia el estado a 'Aprobado' y envía un correo de notificación.
    """
    import models
    from utils import send_approval_email
    
    taller = db.query(models.Taller).filter(models.Taller.id_taller == id_taller).first()
    
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")
        
    if taller.estado_aprobacion == 'Aprobado':
        return {"message": "El taller ya se encuentra aprobado."}

    # Cambiar estado
    taller.estado_aprobacion = 'Aprobado'
    db.commit()
    db.refresh(taller)
    
    # Enviar correo de notificación
    correo_enviado = send_approval_email(destinatario=taller.correo, nombre_taller=taller.razon_social)
    
    mensaje = "Taller aprobado exitosamente."
    if not correo_enviado:
        mensaje += " (Aviso: Hubo un problema enviando el correo de notificación, pero el taller fue aprobado en base de datos)."

    return {
        "status": "success",
        "message": mensaje,
        "estado_actual": taller.estado_aprobacion
    }

@router.get("/{id_taller}/solicitudes")
def get_taller_solicitudes(id_taller: int, db: Session = Depends(get_db)):
    import models
    incidentes = db.query(models.Incidente).filter(models.Incidente.estado_solicitud == 'Pendiente').all()
    resultados = []
    for inc in incidentes:
        resultados.append({
            "id_incidente": inc.id_incidente,
            "tipo_problema": inc.tipo_problema,
            "nivel_prioridad": inc.nivel_prioridad or "Media",
            "cliente": f"{inc.cliente.nombres} {inc.cliente.apellidos}" if inc.cliente else "Conductor en Ruta",
            "vehiculo": f"{inc.vehiculo.marca} {inc.vehiculo.modelo} ({inc.vehiculo.color})" if inc.vehiculo else "Vehículo",
            "transcripcion_audio": inc.descripcion_manual,
            "latitud": inc.ubicacion_latitud,
            "longitud": inc.ubicacion_longitud
        })
    return resultados

@router.post("/{id_taller}/tecnicos", response_model=schemas.TecnicoResponse)
def create_tecnico_endpoint(id_taller: int, tecnico: schemas.TecnicoCreate, db: Session = Depends(get_db)):
    existing = crud.get_tecnico_by_email(db, email=tecnico.correo)
    if existing:
        raise HTTPException(status_code=400, detail="Este correo ya está registrado para un técnico.")
    
    tecnico.id_taller = id_taller
    return crud.create_tecnico(db=db, tecnico=tecnico)

@router.get("/{id_taller}/tecnicos", response_model=list[schemas.TecnicoResponse])
def read_tecnicos(id_taller: int, db: Session = Depends(get_db)):
    return crud.get_tecnicos_by_taller(db=db, id_taller=id_taller)

@router.get("/servicios/todos")
def get_all_servicios(db: Session = Depends(get_db)):
    import models
    
    standard = [
        {"nombre_servicio": "Batería", "tarifa_base_estimada": 50.0},
        {"nombre_servicio": "Motor", "tarifa_base_estimada": 150.0},
        {"nombre_servicio": "Frenos", "tarifa_base_estimada": 80.0},
        {"nombre_servicio": "Llantas", "tarifa_base_estimada": 30.0},
        {"nombre_servicio": "Remolque / Grúa", "tarifa_base_estimada": 120.0},
        {"nombre_servicio": "Cerrajería", "tarifa_base_estimada": 60.0},
        {"nombre_servicio": "Suministro de Combustible", "tarifa_base_estimada": 40.0},
        {"nombre_servicio": "Electricidad en Ruta", "tarifa_base_estimada": 70.0},
        {"nombre_servicio": "Fuga de Aceite / Fluidos", "tarifa_base_estimada": 55.0}
    ]
    
    for s in standard:
        existente = db.query(models.Servicio).filter(models.Servicio.nombre_servicio == s["nombre_servicio"]).first()
        if not existente:
            db_s = models.Servicio(**s)
            db.add(db_s)
    db.commit()
    
    servicios = db.query(models.Servicio).all()
    return [{"id_servicio": s.id_servicio, "nombre_servicio": s.nombre_servicio} for s in servicios]

@router.get("/{id_taller}/servicios")
def get_taller_servicios(id_taller: int, db: Session = Depends(get_db)):
    import models
    ts = db.query(models.TallerServicio).filter(models.TallerServicio.id_taller == id_taller).all()
    return [t.id_servicio for t in ts]

@router.post("/{id_taller}/servicios")
def update_taller_servicios(id_taller: int, payload: dict, db: Session = Depends(get_db)):
    import models
    servicios_ids = payload.get("servicios_ids", [])
    db.query(models.TallerServicio).filter(models.TallerServicio.id_taller == id_taller).delete()
    for sid in servicios_ids:
        t_serv = models.TallerServicio(
            id_taller=id_taller,
            id_servicio=sid,
            precio_especifico_taller=50.0,
            estado_disponible=True
        )
        db.add(t_serv)
    db.commit()
    return {"status": "success", "message": "Servicios del taller actualizados."}

@router.post("/tecnicos/login", response_model=schemas_auth.TokenResponse)
def login_tecnico(request: schemas_auth.LoginRequest, db: Session = Depends(get_db)):
    db_tecnico = crud.get_tecnico_by_email(db, email=request.correo)
    if not db_tecnico or not crud.verify_password(request.password, db_tecnico.password_hash):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    
    return {
        "access_token": "fake-jwt-token-tecnico",
        "token_type": "bearer",
        "user_id": db_tecnico.id_tecnico,
        "user_name": f"{db_tecnico.nombres} {db_tecnico.apellidos}",
        "primer_login": db_tecnico.primer_login
    }

@router.post("/tecnicos/{id_tecnico}/cambiar-password")
def cambiar_password_tecnico(
    id_tecnico: int,
    data: dict,
    db: Session = Depends(get_db)
):
    import models
    tecnico = db.query(models.Tecnico).filter(models.Tecnico.id_tecnico == id_tecnico).first()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
    
    if "new_password" not in data or not data["new_password"]:
        raise HTTPException(status_code=400, detail="La nueva contraseña es requerida")

    tecnico.password_hash = crud.get_password_hash(data["new_password"])
    tecnico.primer_login = False
    db.commit()
    
    return {"message": "Contraseña actualizada correctamente"}
    
@router.post("/tecnicos/{id_tecnico}/resetear-password")
def resetear_password_tecnico(
    id_tecnico: int,
    data: dict,
    db: Session = Depends(get_db)
):
    import models
    tecnico = db.query(models.Tecnico).filter(models.Tecnico.id_tecnico == id_tecnico).first()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
    
    if "new_password" not in data or not data["new_password"]:
        raise HTTPException(status_code=400, detail="La nueva contraseña es requerida")

    tecnico.password_hash = crud.get_password_hash(data["new_password"])
    tecnico.primer_login = True
    db.commit()
    
    return {"message": "Contraseña reseteada correctamente"}

@router.post("/tecnicos/{id_tecnico}/fcm-token")
def update_tecnico_fcm_token(id_tecnico: int, request: schemas.UpdateFCMTokenRequest, db: Session = Depends(get_db)):
    import models
    db_tecnico = db.query(models.Tecnico).filter(models.Tecnico.id_tecnico == id_tecnico).first()
    if not db_tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
    db_tecnico.fcm_token = request.fcm_token
    db.commit()
    return {"message": "Token FCM de Técnico actualizado exitosamente"}

@router.get("/{id_taller}/trabajos")
def get_taller_trabajos(id_taller: int, db: Session = Depends(get_db)):
    import models
    asistencias = db.query(models.Asistencia).filter(models.Asistencia.id_taller == id_taller).all()
    resultados = []
    for asis in asistencias:
        inc = asis.incidente
        if not inc:
            continue
        resultados.append({
            "id_incidente": inc.id_incidente,
            "estado": inc.estado_solicitud,
            "cliente": f"{inc.cliente.nombres} {inc.cliente.apellidos}" if inc.cliente else "Conductor",
            "vehiculo": f"{inc.vehiculo.marca} {inc.vehiculo.modelo}" if inc.vehiculo else "Vehículo",
            "problema": inc.tipo_problema,
            "prioridad": inc.nivel_prioridad or "Media",
            "tecnico": f"{asis.tecnico.nombres} {asis.tecnico.apellidos}" if asis.tecnico else "Sin asignar",
            "monto": 50.0
        })
    return resultados

@router.get("/tecnicos/{id_tecnico}/trabajos")
def get_tecnico_trabajos(id_tecnico: int, db: Session = Depends(get_db)):
    import models
    asistencias = db.query(models.Asistencia).filter(models.Asistencia.id_tecnico == id_tecnico).all()
    
    resultados = []
    for asis in asistencias:
        inc = asis.incidente
        if not inc:
            continue
        resultados.append({
            "id": f"INC-{inc.id_incidente}",
            "id_incidente": inc.id_incidente,
            "estado": inc.estado_solicitud,
            "cliente": f"{inc.cliente.nombres} {inc.cliente.apellidos}",
            "vehiculo": f"{inc.vehiculo.marca} {inc.vehiculo.modelo} ({inc.vehiculo.color}) | Placa: {inc.vehiculo.placa} | Año: {inc.vehiculo.año} | Transmisión: {inc.vehiculo.tipo_transmision}",
            "problema": inc.tipo_problema,
            "prioridad": inc.nivel_prioridad or "Media",
            "lat": inc.ubicacion_latitud,
            "lng": inc.ubicacion_longitud
        })
    return resultados

@router.post("/tecnicos/{id_tecnico}/ubicacion")
def update_tecnico_ubicacion(id_tecnico: int, request: dict, db: Session = Depends(get_db)):
    import models
    tecnico = db.query(models.Tecnico).filter(models.Tecnico.id_tecnico == id_tecnico).first()
    if not tecnico:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
        
    if "latitud" not in request or "longitud" not in request:
        raise HTTPException(status_code=400, detail="Latitud y Longitud requeridas")
        
    tecnico.ubicacion_actual_latitud = request["latitud"]
    tecnico.ubicacion_actual_longitud = request["longitud"]
    db.commit()
    return {"status": "success", "message": "Ubicación actualizada"}
