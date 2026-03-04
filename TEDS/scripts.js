// CONFIGURACIÓN DE CREDENCIALES
const AZURE_ENDPOINT = "https://face-mpv.cognitiveservices.azure.com";
const SUBSCRIPTION_KEY = "AnTg6Uzlo1eHaQLad6r9S1j0K4woOaYoHDJUcnLEFngSYML35ptPJQQJ99CCAC8vTInXJ3w3AAAKACOGr4jH";

// AJUSTES DE SENSIBILIDAD (Teclado Friendly)
const UMBRAL_YAW = 35;         
const UMBRAL_PITCH_DOWN = 45;  
const UMBRAL_PITCH_UP = 20;    
const UMBRAL_ALEJAMIENTO = 75; 
const FRECUENCIA_SCAN = 1000; // Análisis cada 1 segundo

// Referencias del DOM
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const estadoTexto = document.getElementById('estado');
const barra = document.getElementById('barra');
const textoBarra = document.getElementById('texto-barra');
const capaBloqueo = document.getElementById('capa-bloqueo');
const ctx = canvas.getContext('2d');

// Variables de control
let tiempoAnterior = Date.now();
let nivelDistraccion = 0.0;
const LIMITE_SEGUNDOS = 5.0;
const TASA_RECUPERACION = 1.2;
let alertaActiva = false;

// Iniciar cámara al cargar
navigator.mediaDevices.getUserMedia({ video: true })
    .then(stream => { 
        video.srcObject = stream; 
        estadoTexto.innerText = "Sistema Activo - Escaneando...";
    })
    .catch(err => { 
        estadoTexto.innerText = "Error: No se encontró cámara."; 
    });

// Función para cerrar el recuadro
function cerrarAlerta() {
    capaBloqueo.style.display = "none";
    nivelDistraccion = 0;
    alertaActiva = false;
    tiempoAnterior = Date.now();
}

// Bucle de análisis
async function analizarFrame() {
    if (alertaActiva) return;

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    
    canvas.toBlob(async (blob) => {
        if (!blob) return;

        const url = `${AZURE_ENDPOINT}/face/v1.0/detect?returnFaceAttributes=headPose`;

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY,
                    'Content-Type': 'application/octet-stream'
                },
                body: blob
            });

            const faces = await response.json();
            
            let tiempoActual = Date.now();
            let deltaT = (tiempoActual - tiempoAnterior) / 1000;
            tiempoAnterior = tiempoActual;
            
            let estaDistraido = false;

            if (!faces || faces.length === 0) {
                estadoTexto.innerText = "Estado: Rostro no detectado";
                estadoTexto.className = "texto-alerta";
                estaDistraido = true;
            } 
            else {
                const faceRect = faces[0].faceRectangle;
                const headPose = faces[0].faceAttributes.headPose;
                
                let muyLejos = faceRect.width < UMBRAL_ALEJAMIENTO;
                let distraidoYaw = Math.abs(headPose.yaw) > UMBRAL_YAW;
                let distraidoPitch = (headPose.pitch > UMBRAL_PITCH_DOWN) || (headPose.pitch < -UMBRAL_PITCH_UP);

                if (muyLejos || distraidoYaw || distraidoPitch) {
                    estadoTexto.innerText = "Estado: Distraído";
                    estadoTexto.className = "texto-alerta";
                    estaDistraido = true;
                } else {
                    estadoTexto.innerText = "Estado: Concentrado";
                    estadoTexto.className = "";
                    estaDistraido = false;
                }
            }

            // Lógica de la barra
            if (estaDistraido) {
                nivelDistraccion += deltaT;
            } else {
                nivelDistraccion -= (deltaT * TASA_RECUPERACION);
            }

            nivelDistraccion = Math.max(0, Math.min(nivelDistraccion, LIMITE_SEGUNDOS));

            // Actualizar Interfaz
            let porcentaje = (nivelDistraccion / LIMITE_SEGUNDOS) * 100;
            barra.style.width = porcentaje + "%";
            textoBarra.innerText = `Nivel de distracción: ${nivelDistraccion.toFixed(1)}s / ${LIMITE_SEGUNDOS}s`;

            if (porcentaje < 40) barra.style.backgroundColor = "#2ecc71";
            else if (porcentaje < 80) barra.style.backgroundColor = "#f1c40f";
            else barra.style.backgroundColor = "#e74c3c";

            if (nivelDistraccion >= LIMITE_SEGUNDOS) {
                alertaActiva = true;
                capaBloqueo.style.display = "flex";
            }

        } catch (error) {
            console.error("Error en API Azure:", error);
        }
    }, 'image/jpeg');
}

setInterval(analizarFrame, FRECUENCIA_SCAN);