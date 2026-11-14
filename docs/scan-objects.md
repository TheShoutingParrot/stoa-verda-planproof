# Local door, window and plumbing counts

Planproof can count windows, doors, toilet bowls and sinks on a supplied PNG using CubiCasa's published multi-task hourglass network. One pass at four orientations builds an inventory for all four questions. The reader uses the model’s directional endpoint maps to pair the ends of windows and doors along each wall. It checks the ink between endpoints against the model’s window and door probabilities. Competing openings on the same wall are resolved together, and strong semantic components can supply diagonal or cropped openings. Toilet bowls and sinks use connected fixture masks. Each result links to a box on the original scan. The model can miss small symbols or merge adjacent symbols. A rendered zero means that no qualifying symbol was detected.

The reader takes the supplied image bytes and question. It checks SHA-256 before reusing any inventory across questions, holds at most 16 small inventories in memory, and serializes local inference. The default interpreter can still use other readers if these optional dependencies or model assets are missing.

## Install and run

Run these commands from the Planproof checkout. The verified environment uses Python 3.12 and PyTorch 2.15.0. Installation downloads the public upstream architecture and checkpoint once. The server uses local files at inference time. Apple Silicon uses MPS when available. Systems with CUDA use CUDA, and other systems use CPU.

```sh
mkdir -p .local/scan-dev/objects
python3.12 -m venv .local/scan-dev/objects/venv
.local/scan-dev/objects/venv/bin/python -m pip install torch==2.15.0 numpy==2.5.4 opencv-python-headless==5.0.0.93 pillow==13.0.0
git clone https://github.com/CubiCasa/CubiCasa5k.git .local/scan-dev/objects/CubiCasa5k
git -C .local/scan-dev/objects/CubiCasa5k checkout c34440266665a11f4484eb06cd2e4b7d72ad76c1
curl -fL --retry 2 -o .local/scan-dev/objects/model_best_val_loss_var.pkl 'https://drive.usercontent.google.com/download?id=1gRB7ez1e4H7a9Y09lLqRuna0luZO5VRK&export=download&confirm=t'
.local/scan-dev/objects/venv/bin/python -m unittest discover -s tests -p test_scan_objects.py
.local/scan-dev/objects/venv/bin/python server.py
```

`PLANPROOF_CUBICASA_CODE` can point to a different checkout of the same upstream commit. `PLANPROOF_OBJECT_WEIGHTS` can point to the downloaded checkpoint elsewhere. The loader verifies hashes of the upstream Python modules and checks the weight file against SHA-256 `dd20b4e1bf1d670f2125107b079df06958b1ccd36e49a464ab739aeb00b8e7a2` before restricted PyTorch `weights_only=True` deserialization. `scripts.scan_objects.available()` checks the local prerequisites without loading tensors. The server should be started with the interpreter that has these packages.

## Source and evaluation scope

Ahti Kalervo, Juha Ylioinas, Markus Häikiö, Antti Karhu and Juho Kannala published this CubiCasa5K model. The upstream repository states CC BY-NC 4.0 and links the checkpoint in its evaluation instructions. The original floor-plan dataset carries CC BY-NC-SA 4.0. The checkpoint and upstream source stay in the ignored local asset directory. [CubiCasa release and evaluation instructions](https://github.com/CubiCasa/CubiCasa5k/tree/c34440266665a11f4484eb06cd2e4b7d72ad76c1) · [Upstream licence](https://github.com/CubiCasa/CubiCasa5k/blob/c34440266665a11f4484eb06cd2e4b7d72ad76c1/LICENSE) · [Original dataset](https://doi.org/10.5281/zenodo.2613548)

Matching filenames from the original split manifests against Stoa's 4,787 CubiCasa PNGs gives 4,018 training drawings, 382 validation drawings and 387 original test drawings. The model trained on many released Stoa drawings. Report performance on the original test partition separately and preserve any independently held-out subset for evaluation. The detector reads no vector annotations, benchmark answers or filenames.
