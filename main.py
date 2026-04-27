from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from database import engine
import models
import os

models.Base.metadata.create_all(bind=engine)

os.makedirs("uploads", exist_ok=True)

app = FastAPI(
    title="API - Plataforma Inteligente de Emergencias Vehiculares",
    description="Backend para la gestión de incidentes vehiculares, talleres y técnicos",
    version="1.0.0"
)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Configuración de CORS para permitir peticiones desde Flutter y Angular
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción cambiar por dominios específicos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, id_taller: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[id_taller] = websocket

    def disconnect(self, id_taller: int):
        if id_taller in self.active_connections:
            del self.active_connections[id_taller]

    async def send_personal_message(self, message: dict, id_taller: int):
        print(f"📣 Intentando enviar alerta al taller ID {id_taller}", flush=True)
        if id_taller in self.active_connections:
            try:
                await self.active_connections[id_taller].send_json(message)
                print(f"✅ Alerta enviada con éxito al taller ID {id_taller}", flush=True)
            except Exception as e:
                print(f"❌ Falló envío al taller ID {id_taller}: {e}", flush=True)
                self.disconnect(id_taller)
        else:
            print(f"⚠️ El taller ID {id_taller} NO está conectado por WebSocket. Conexiones activas: {list(self.active_connections.keys())}", flush=True)

manager = ConnectionManager()

@app.websocket("/ws/talleres/{id_taller}")
async def websocket_endpoint(websocket: WebSocket, id_taller: int):
    await manager.connect(id_taller, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(id_taller)

@app.get("/")
def read_root():
    return {
        "status": "up",
        "message": "Bienvenido a la API de Plataforma Inteligente de Emergencias Vehiculares"
    }

from routers import clientes, talleres, incidentes, pagos, admin, auth

app.include_router(clientes.router, prefix="/api/clientes", tags=["Clientes"])
app.include_router(talleres.router, prefix="/api/talleres", tags=["Talleres"])
app.include_router(incidentes.router, prefix="/api/incidentes", tags=["Incidentes"])
app.include_router(pagos.router)
app.include_router(admin.router)
app.include_router(auth.router, prefix="/api/auth", tags=["Autenticación"])
