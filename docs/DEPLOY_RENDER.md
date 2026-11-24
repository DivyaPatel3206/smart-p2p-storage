# Deploying on Render (3 nodes + React dashboard)

The repo contains a **`render.yaml` Blueprint** that creates four things on Render:

| Service | Type | What it is |
|---|---|---|
| `p2p-node1` | Python web service | node1, zone-A (the bootstrap node) |
| `p2p-node2` | Python web service | node2, zone-B, bootstraps from node1's public URL |
| `p2p-node3` | Python web service | node3, zone-A, bootstraps from node1's public URL |
| `p2p-dashboard` | Static site | the React dashboard (`frontend/`, built with Vite) |

All three nodes share one random `SWARM_KEY` through an environment group, so they trust each other.
Each node learns its own public address from Render's `RENDER_EXTERNAL_URL` /
`RENDER_EXTERNAL_HOSTNAME` variables and reaches its peers over **HTTPS**. Free services cannot use
Render's private network.

## Easiest: ONE service (use this if Render says "will exceed limit of 25")

`scripts/cloud_start.py` runs the 3 nodes as separate processes **inside one Render service**, plus a
small gateway that serves the dashboard and forwards `/n/1`, `/n/2`, `/n/3` to the nodes. It needs only **1 free slot**.

- **Blueprint:** New → Blueprint → your repo → **Blueprint Path: `render-single.yaml`** → Deploy.
- **Or by hand:** New → **Web Service** → your repo, then:
  - Runtime **Python 3**
  - Build `pip install -r requirements-core.txt`
  - Start `python scripts/cloud_start.py`
  - Health check `/healthz`
  - Environment `PYTHON_VERSION=3.12.7`
  - Instance type **Free**

Open the service URL: the dashboard appears straight away, with no `VITE_NODES` needed. Network tab → **Simulate a node
failure** stops/starts node2 or node3 for the viva. The prebuilt dashboard lives in `backend/dashboard_dist/`;
after changing the frontend, rebuild it with `cd frontend && npm run build:cluster`.

## Step 1 — Put the project on GitHub

In the VS Code terminal, inside `smart-p2p-storage`:

```bash
git init
git add .
git commit -m "Smart P2P Storage"
git branch -M main
git remote add origin https://github.com/<your-username>/smart-p2p-storage.git
git push -u origin main
```

Create the empty repository on github.com first. `data/`, `samples/` and `node_modules/` are ignored by `.gitignore`.

## Step 2 — Create the Blueprint

1. Log in at dashboard.render.com, then **New → Blueprint**.
2. Connect GitHub and pick the `smart-p2p-storage` repo. Render reads `render.yaml`.
3. It asks for **`VITE_NODES`**. Leave it **empty** for now; you'll set it in Step 4.
4. Click **Apply** / **Deploy Blueprint**. The first build takes a few minutes.

## Step 3 — Check the nodes

Open each node service in Render. Its URL looks like `https://p2p-node1-xxxx.onrender.com`. Then:

- Open `https://<node1-url>/healthz`. You should see `{"ok": true, "node": "node1"}`.
- Open `https://<node1-url>/api/peers`. After about a minute it should list node2 and node3 with `"alive": true`.
- The **Logs** tab shows lines like `[node2] https://p2p-node2-xxxx.onrender.com zone=zone-B ...`.

## Step 4 — Point the dashboard at a node

1. Open the `p2p-dashboard` service, go to **Environment**, and set
   `VITE_NODES = https://p2p-node1-xxxx.onrender.com` (your real node1 URL).
   You can list all three separated by commas, but one is enough: the dashboard adds the other nodes
   from node1's peer list automatically.
2. **Save**, then **Manual Deploy → Deploy latest commit**. Vite bakes this value in at build time, so the site has to be rebuilt.
3. Open the dashboard URL, for example `https://p2p-dashboard-xxxx.onrender.com`.

Shortcut that needs no rebuild: `https://<dashboard-url>/?node=https://<node1-url>`

## Things to know about the free plan

- **Memory:** each free service has 512 MB RAM, which is too small for torch + BLIP + DistilBART. The nodes install
  `requirements-core.txt` and use the labelled fallback summariser and captioner. Run the real models on your
  laptop for the AI evaluation numbers. To run them in the cloud, use a paid instance with ≥ 2 GB RAM and change the build
  command to `pip install -r requirements.txt`.
- **Files are not permanent:** a restart, redeploy or spin-down erases that node's chunks. Because every chunk has k = 2 copies
  in different zones, the other nodes re-replicate it. That's a good viva demo, but if two nodes restart at the same time, data is
  lost. For permanent storage: paid instance, add a **Disk** mounted at e.g. `/var/data`, and set `DATA_DIR=/var/data`.
- **Instance hours:** free services sleep after 15 minutes without traffic, but the nodes' heartbeats keep
  each other awake. Three always-on nodes use about 72 of the workspace's **750 free hours per month** each day, so about 10 days.
  **Suspend** the three node services (Settings → Suspend) when you're not demoing, and resume them about 5 minutes before your viva.
- **Cold start:** a sleeping service takes up to about a minute to wake. If the dashboard shows red, wait a minute and refresh.

## Without the Blueprint (manual setup)

Create **three Web Services** from the repo with:

- Runtime **Python 3**
- Build command `pip install -r requirements-core.txt`
- Start command `python backend/node.py`
- Health check `/healthz`
- Environment:

| Key | node1 | node2 | node3 |
|---|---|---|---|
| `SWARM_KEY` | same long random text on all three | same | same |
| `NODE_NAME` | node1 | node2 | node3 |
| `NODE_ZONE` | zone-A | zone-B | zone-A |
| `BOOTSTRAP` | – | `https://<node1-url>` | `https://<node1-url>` |
| `PYTHON_VERSION` | 3.12.7 | 3.12.7 | 3.12.7 |

Then create a **Static Site** with:

- Root directory `frontend`
- Build command `npm install && npm run build`
- Publish directory `dist`
- Environment: `VITE_NODES=https://<node1-url>` and `NODE_VERSION=22.12.0`

## Troubleshooting

| Symptom | Fix |
|---|---|
| Node log: `403 bad swarm signature` | The `SWARM_KEY`s differ. Use the env group (Blueprint) or copy exactly the same value to all nodes. |
| `/api/peers` empty on node2 | `BOOTSTRAP` / `BOOTSTRAP_HOST` is missing, or node1 was still starting. It retries every few seconds, so wait. |
| Dashboard red, "Failed to fetch" | `VITE_NODES` not set or the site wasn't redeployed after setting it. The URL must start with `https://`. The node may be waking up. |
| Build fails on Python version | Keep `PYTHON_VERSION=3.12.7` (or another full version number that Render supports). |
| Build fails in `p2p-dashboard` | Make sure `NODE_VERSION` is 20.19+ or 22.12+ (Vite 7). |
