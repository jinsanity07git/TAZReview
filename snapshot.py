import os
import pickle
version_min = (0, 1, 3)
furl = os.path.join("./vr","tdm23_env.vr")
with open(furl, "rb") as f:
    tdmvr = pickle.load(f)
if tdmvr.version_info >= version_min:
    print (tdmvr.version_info)
else:
    raise Exception("Please use the right version : tdm23_env.vr-v" + ".".join(map(str, version_min)))

if __name__ == "__main__":

    notebook_path = './Taz_Explainations.ipynb'
    output_path = f'./outputs/report.html'
    tdmvr.shot_run(notebook_path, output_path )
