##################################################################
# 1. Test del baseline scheduler
##################################################################

# Server
# uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000
python -m uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000 # mejor modular
#INFO:     Will watch for changes in these directories: ['/home/mario/master/TFM/distributed-scheduler']
#INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
#INFO:     Started reloader process [17406] using StatReload
#INFO:     Started server process [17460]
#INFO:     Waiting for application startup.
#INFO:     Application startup complete.

#INFO:     127.0.0.1:49402 - "GET / HTTP/1.1" 200 OK
#INFO:     127.0.0.1:33082 - "POST /heartbeat HTTP/1.1" 200 OK
#INFO:     127.0.0.1:45738 - "GET /nodes HTTP/1.1" 200 OK

## 1.1 Test root
curl localhost:8000
# Client       
#{"status":"scheduler running"}% 

# Server
#INFO:     127.0.0.1:49402 - "GET / HTTP/1.1" 200 OK


## 1.2 Test heartbeat
curl -X POST localhost:8000/heartbeat \
-H "Content-Type: application/json" \
-d '{
  "node_id": "node-1",
  "hostname": "test-machine",
  "capabilities": {
    "cpus": 4,
    "memory_mb": 8192,
    "gpu": false,
    "architecture": "x86_64"
  },
  "current_load": 0.2
}'
# Client
# {"status":"ok","registered_node":"node-1"}%   

# Server
#INFO:     127.0.0.1:33082 - "POST /heartbeat HTTP/1.1" 200 OK


### See nodes
curl localhost:8000/nodes
# Client
# [
#    {
#       "node_id":"node-1",
#       "hostname":"test-machine",
#       "capabilities":{
#                       "cpus":4,
#                       "memory_mb":8192,
#                       "gpu":false,
#                       "architecture":"x86_64"
#                       },
#       "current_load":0.2
#     }
# ]

# Server
#INFO:     127.0.0.1:45738 - "GET /nodes HTTP/1.1" 200 OK


## 1.3 Test scheduling
curl -X POST localhost:8000/jobs \
-H "Content-Type: application/json" \
-d '{
  "job_id": "job-1",
  "image": "ubuntu",
  "command": "echo hello"
}'
# Client
# {"job_id":"job-1","selected_node":"node-1","image":"ubuntu","command":"echo hello"}
# err if no nodes: {"detail":"No nodes available"}

# Server
# INFO:     127.0.0.1:53928 - "POST /jobs HTTP/1.1" 200 OK
# err if no nodes -> no jobs: 
# INFO:     127.0.0.1:37316 - "POST /jobs HTTP/1.1" 503 Service Unavailable

### See jobs
curl localhost:8000/jobs
# No hay un @app.get("\jobs") definido en main.py


##################################################################
# 2. Probar agent.main y Round Robin
##################################################################

## Levantamos el scheduler
python -m uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

# Levantamos un agente (1 por terminal)
NODE_ID=node-1 AGENT_PORT=9001 python -m agent.main
NODE_ID=node-2 AGENT_PORT=9002 python -m agent.main
# Va mandando heartbeats cada 5 s perfecto

## Listamos 2 nodos:
curl localhost:8000/nodes
#[
#  {
#    "node_id":"node-1",
#    "hostname":"fedora",
#    "capabilities":{
#      "cpus":12,
#      "memory_mb":32007,
#      "gpu":false,
#      "architecture":"x86_64"
#      },
#    "current_load":0.023
#  },
#  
#  {
#    "node_id":"node-2",
#    "hostname":"fedora",
#    "capabilities":{
#      "cpus":12,
#      "memory_mb":32007,
#      "gpu":false,
#      "architecture":"x86_64"
#      },
#    "current_load":0.017
#  }
#]

## Posteamos 3 trabajos:
curl -X POST localhost:8000/jobs \
     -H "Content-Type: application/json" \
     -d '{
       "job_id": "job-1",
       "image": "ubuntu"
     }'
# {"job_id":"job-1","selected_node":"node-1","image":"ubuntu","command":null}


curl -X POST localhost:8000/jobs \
     -H "Content-Type: application/json" \
     -d '{
       "job_id": "job-2",
       "image": "ubuntu"
     }'
# {"job_id":"job-2","selected_node":"node-2","image":"ubuntu","command":null}


curl -X POST localhost:8000/jobs \
     -H "Content-Type: application/json" \
     -d '{
       "job_id": "job-3",
       "image": "ubuntu"
     }'
# {"job_id":"job-3","selected_node":"node-1","image":"ubuntu","command":null}

## Observamos que job-1 -> node-1, job-2 -> node-2 y job-3 -> node-3

# Perfecto

##################################################################
# 3. Probar el scheduler (Added: queing jobs state)
##################################################################

# Lanzamos scheduler (T1)
python -m uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

# Lanzamos nodos
NODE_ID=nodeA AGENT_PORT=9001 python -m agent.main # T2
NODE_ID=nodeB AGENT_PORT=9002 python -m agent.main # T3

# Lanzamos trabajos (misma terminal, T4)
for i in {1..5}; do
curl -X POST localhost:8000/jobs \
-H "Content-Type: application/json" \
-d "{
  \"job_id\":\"job$i\",
  \"image\":\"alpine\",
  \"command\":\"sleep 5\"
}"
done

"""
Observamos que el scheduler asigna tareas de manera completamente secuencial;
es decir, aun teniendo varios nodos disponibles, hasta no recibir status=completed,
no asigna otra tarea a otro nodo. Tardando un total de 25 segundos en realizar una
tarea que debería haber completado en 15 segundos con 2 nodos.

Tenemos que implementar async dispatch.

Cómo hacemos esto?

Muy fácil, encapsulamos la parte del loop del dispatcher que se encarga de asignar
tareas a nodos en una función y la llamamos desde el loop principal de forma asíncrona
(antes estábamos llamándola una vez por loop). Para llamarla de forma asíncrona usando
threads:

Llamada secuencial:
dispatch_job(job, selected_node)

Llamada asíncrona:
threading.Thread(
            target=dispatch_job,
            args=(job, selected_node),
            daemon=True
        ).start()


Ejecutando el mismo código de antes, observamos que ahora todos los trabajos se cogen al
momento y, aproximadamente, a los 5 s todos terminan:
[completed] job=job1 status=200
[completed] job=job2 status=200
[completed] job=job4 status=200
[completed] job=job5 status=200
[completed] job=job3 status=200

PROBLEMA: el scheduler no contempla restricciones en la máxima cantidad de trabajos que
podemos asignar a un nodo. Vamos a meter 50 trabajos, no se han quejao pero xd.
"""