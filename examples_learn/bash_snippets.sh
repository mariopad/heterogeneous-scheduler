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

##################################################################
# 4. Probar el scheduler (evitando oversubscription)
##################################################################
# Vamos a settear max_parallel_jobs=1 solo para validar -> CAMBIALO: node_has_capacity()
""""
Experimento:
- 2 agentes
- 10 jobs (sleep 5)

Deberiamos ver:
nodeA, nodeB cada uno con 1 job bloqueados
8 trabajos en cola

Duracion total aproximada de 25 s (10*5/2)
""""

# Lanzamos scheduler (T1)
python -m uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

# Lanzamos nodos
NODE_ID=nodeA AGENT_PORT=9001 python -m agent.main # T2
NODE_ID=nodeB AGENT_PORT=9002 python -m agent.main # T3

# Lanzamos trabajos (misma terminal, T4)
for i in {1..10}; do
curl -X POST localhost:8000/jobs \
-H "Content-Type: application/json" \
-d "{
  \"job_id\":\"job$i\",
  \"image\":\"alpine\",
  \"command\":\"sleep 5\"
}"
done

"""
Ocurre lo que esperábamos: 
  - Tamaño de cola=8 para el décimo trabajo
  - Hasta que no acaban los trabajos no se asignan nuevos trabajos
    a los nodos

Sin embargo, cuando no hay nodos disponibles, sigue iterando sobre los
jobs. Esto no está bien.

Solución: solo sacar trabajos de la cola si hay nodos disponibles

Consecuencia: cluster_state.dequeue_job() bloquea; el dispatcher se queda
esperando en esta llamada hasta que llegue un trabajo
"""

##################################################################
# 5. Probar node expiration strategy
##################################################################

"""
El scheduler, hasta ahora, contemplaba los nodos que mandan al menos
un heartbeat.

El objetivo de este nuevo commit es dejar de considerar los nodos que
no han dado pruebas de vida en un intervalo determinado de tiempo, 15s
en nuestro caso.

Para ello, ejecutamos un daemon que verifica que la última señal de
vida esté en un intervalo razonable de tiempo. Si no lo está, elimina
al nodo.

Si el nodo volviese a estar vivo, como es lo que se simula en este
experimento, el nodo vuelve a aparecer considerado por el scheduler.
"""

# Lanzamos scheduler (T1)
python -m uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

# Lanzamos nodos
NODE_ID=nodeA AGENT_PORT=9001 python -m agent.main # T2
NODE_ID=nodeB AGENT_PORT=9002 python -m agent.main # T3

# Hacemos curl 
curl localhost:8000/cluster
#{"nodes":2...}

# Ctrl + C sobre uno de los nodos -> Lo desconectamos

# Esperamos hasta ver el log: [expiration] removing node=nodeb

# Volvemos a hacer curl
curl localhost:8000/cluster
#{"nodes":1...}

# Activamos de nuevo el nodo que hemos apagado y esperamos a 1 HB
curl localhost:8000/cluster
#{"nodes":2...}

"""
Todo funciona como se esperaba; sin embargo, aparece un nuevo problema:
  - Gestionar qué hacer con los trabajos de los que se estaba encargando
  el nodo caído
"""

##################################################################
# 6. Test benchmark + parallelization + async +...
##################################################################
# Everything works fine!

# Launch scheduler (T1)
python -m uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

# Lanzamos nodos (logical cores)
NODE_ID=nodeA AGENT_PORT=9001 python -m agent.main # (T2)

# Lanzamos trabajos (T3)
for i in {1..16}; do
curl -X POST localhost:8000/jobs \
-H "Content-Type: application/json" \
-d "{
  \"job_id\":\"job$i\",
  \"image\":\"alpine\",
  \"command\":\"sleep 5\"
}"
done
# Scheduler logs -> think about also storing them in a file
"""
INFO:     127.0.0.1:55132 - "POST /heartbeat HTTP/1.1" 200 OK
[dispatcher] picked job=job1
INFO:     127.0.0.1:55134 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job1 node=nodeA
[dispatcher] picked job=job2
INFO:     127.0.0.1:55138 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job2 node=nodeA
[dispatch] job=job1 accepted, status=200
[dispatch] job=job2 accepted, status=200
[dispatcher] picked job=job3
[dispatch] job=job3 node=nodeA
INFO:     127.0.0.1:55150 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job3 accepted, status=200
[dispatcher] picked job=job4
INFO:     127.0.0.1:55164 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job4 node=nodeA
[dispatch] job=job4 accepted, status=200
[dispatcher] picked job=job5
[dispatch] job=job5 node=nodeA
INFO:     127.0.0.1:55168 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job5 accepted, status=200
[dispatcher] picked job=job6
[dispatch] job=job6 node=nodeA
INFO:     127.0.0.1:55184 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job6 accepted, status=200
[dispatcher] picked job=job7
INFO:     127.0.0.1:55192 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job7 node=nodeA
[dispatch] job=job7 accepted, status=200
[dispatcher] picked job=job8
INFO:     127.0.0.1:36756 - "POST /jobs HTTP/1.1" 200 OK
[dispatch] job=job8 node=nodeA
[dispatcher] all nodes busy
[dispatch] job=job8 accepted, status=200
INFO:     127.0.0.1:36772 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36788 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36794 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36798 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36804 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36812 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36824 - "POST /jobs HTTP/1.1" 200 OK
INFO:     127.0.0.1:36836 - "POST /jobs HTTP/1.1" 200 OK
[dispatcher] all nodes busy
[dispatcher] all nodes busy
INFO:     127.0.0.1:36848 - "POST /heartbeat HTTP/1.1" 200 OK
[dispatcher] all nodes busy
[dispatcher] all nodes busy
[dispatcher] all nodes busy
[dispatcher] all nodes busy
[callback] job=job2 success=True runtime=6.6323089599609375
INFO:     127.0.0.1:36856 - "POST /job_callback HTTP/1.1" 200 OK
[callback] job=job1 success=True runtime=6.707631826400757
INFO:     127.0.0.1:36858 - "POST /job_callback HTTP/1.1" 200 OK
[callback] job=job3 success=True runtime=6.925955772399902
INFO:     127.0.0.1:36862 - "POST /job_callback HTTP/1.1" 200 OK
[callback] job=job4 success=True runtime=6.9032745361328125
INFO:     127.0.0.1:36876 - "POST /job_callback HTTP/1.1" 200 OK
[callback] job=job5 success=True runtime=7.033919334411621
INFO:     127.0.0.1:36886 - "POST /job_callback HTTP/1.1" 200 OK
[dispatcher] picked job=job9
[dispatch] job=job9 node=nodeA
[dispatcher] picked job=job10
[dispatch] job=job10 node=nodeA
[dispatcher] picked job=job11
[dispatch] job=job11 node=nodeA
[dispatcher] picked job=job12
[dispatch] job=job12 node=nodeA
[dispatcher] picked job=job13
[dispatch] job=job13 node=nodeA
[dispatcher] all nodes busy
[dispatch] job=job12 accepted, status=200
[callback] job=job7 success=True runtime=7.061209440231323
INFO:     127.0.0.1:36902 - "POST /job_callback HTTP/1.1" 200 OK
[dispatch] job=job9 accepted, status=200
[dispatch] job=job10 accepted, status=200
[dispatch] job=job11 accepted, status=200
[dispatch] job=job13 accepted, status=200
[callback] job=job8 success=True runtime=7.057347059249878
INFO:     127.0.0.1:36904 - "POST /job_callback HTTP/1.1" 200 OK
[callback] job=job6 success=True runtime=7.146275520324707
INFO:     127.0.0.1:36916 - "POST /job_callback HTTP/1.1" 200 OK
[dispatcher] picked job=job14
[dispatch] job=job14 node=nodeA
"""

"""
- [x] Async execution
- [x] 8 logical cores
- [x] 5 s task + overhead
- [x] Benchmarking works -> GIL is being freed :)
"""


##################################################################
# 7. Measure docker overhead
##################################################################

time docker run --rm alpine sleep 5
"""
total    0m5.804s
user     0m0.020s
sys      0m0.030s
"""