import os
from fastapi import APIRouter, Depends, HTTPException
import stripe
from database import get_db
from sqlalchemy.orm import Session
import models

router = APIRouter(prefix="/api/pagos", tags=["pagos"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

@router.post("/crear-intento")
def crear_intento_pago(payload: dict, db: Session = Depends(get_db)):
    id_incidente = payload.get("id_incidente")
    monto = payload.get("monto", 5000) # 50.00 USD por defecto
    
    if not id_incidente:
        raise HTTPException(status_code=400, detail="Falta el ID del incidente")

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(monto),
            currency="usd",
            automatic_payment_methods={
                "enabled": True,
            },
        )
        
        # Intentar guardar el registro en la BD (Fase 4)
        asistencia = db.query(models.Asistencia).filter(models.Asistencia.id_incidente == id_incidente).first()
        if asistencia:
            pago_existente = db.query(models.Pago).filter(models.Pago.id_asistencia == asistencia.id_asistencia).first()
            if not pago_existente:
                nuevo_pago = models.Pago(
                    id_asistencia=asistencia.id_asistencia,
                    monto_subtotal=monto / 100,
                    monto_comision_plataforma=(monto / 100) * 0.10,
                    monto_total_cliente=monto / 100,
                    metodo_pago="Tarjeta de Crédito (Stripe)",
                    estado_transaccion="Pendiente"
                )
                db.add(nuevo_pago)
                db.commit()

        return {
            "paymentIntent": intent['client_secret'],
            "publishableKey": os.getenv("STRIPE_PUBLISHABLE_KEY")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cliente/{id_cliente}")
def get_cliente_pagos(id_cliente: int, db: Session = Depends(get_db)):
    import models
    incidentes = db.query(models.Incidente).filter(models.Incidente.id_cliente == id_cliente).all()
    if not incidentes:
        return []
        
    id_incidentes = [inc.id_incidente for inc in incidentes]
    asistencias = db.query(models.Asistencia).filter(models.Asistencia.id_incidente.in_(id_incidentes)).all()
    if not asistencias:
        return []
        
    id_asistencias = [asis.id_asistencia for asis in asistencias]
    pagos = db.query(models.Pago).filter(models.Pago.id_asistencia.in_(id_asistencias)).all()
    
    resultados = []
    for pago in pagos:
        asis = pago.asistencia
        inc = asis.incidente if asis else None
        
        resultados.append({
            "id_pago": pago.id_pago,
            "id_asistencia": pago.id_asistencia,
            "monto": float(pago.monto_total_cliente),
            "metodo": pago.metodo_pago,
            "estado": pago.estado_transaccion,
            "fecha": inc.fecha_hora_reporte.strftime("%Y-%m-%d %H:%M") if inc and inc.fecha_hora_reporte else "N/A",
            "taller": asis.taller.nombre_taller if asis and asis.taller else "Taller Desconocido"
        })
        
    return resultados
