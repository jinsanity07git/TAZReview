import os
import sys
"""
This section sets up the project environment, including path configuration
"""
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
from snapshot import tdmvr
##
DIRNAME = "TAZReview"
targs_name = "TAZ-Reviewer"
import gradio as gr
root = current_dir
shot_run = tdmvr.shot_run

ORIROOT = os.getcwd()
def resolve_nburl(inbname):
    notebook_path = tdmvr.path_join(root,f'{inbname}.ipynb')
    return notebook_path

def utl_tool(dirname,inbname,wftag,**kwargs):
    """
    """    
    notebook_path = resolve_nburl(inbname)
    os.chdir(root)
    output_path   = tdmvr.path_join(root, "outputs", f'{inbname}_report.html')

    shot_run(notebook_path, output_path,parameters=kwargs,wftag=wftag )

    with open(output_path,"r",encoding="utf-8") as f:
        outtext = f.read()
    html_content = outtext.replace("\"", "&quot;")
    os.chdir(ORIROOT)
    return (f'<iframe srcdoc="{html_content}" width="100%" height="600px"></iframe>', 
            output_path)

def create_app(title=targs_name,
               dirname=DIRNAME,
               inbname="csv2chord",
               wftag = None
                 ):

    ui_inputs = [
        gr.Textbox(value=""",source,target,value
0,0,0,9622
1,0,1,26598
2,0,2,6392
3,0,3,1782
4,0,4,1063
5,0,5,647
6,0,6,113
7,0,7,2
8,1,0,26539
9,1,1,313129
10,1,2,92552
11,1,3,20102
12,1,4,7240
13,1,5,4175
14,1,6,644
15,1,7,13
""", label="dfcsv")]
    
    ######
    def runner(*args):
        kwargs = {ui_inputs[i].label: arg for i, arg in enumerate(args)}
        try:
            res = utl_tool(dirname,inbname,wftag,**kwargs)
        except Exception as err: 
            res = parse_traceback(err)
            os.chdir(ORIROOT)
        return res
    
    if wftag is not None:
        title = f"{title}-{wftag}"  
    notebook_path = resolve_nburl(inbname)
    demo = gr.Interface(
                        head = ga_script,
                        title=title,
                        description = descurl.format(notebook_path),
                        inputs= ui_inputs,
                        fn=runner ,
                        outputs=[gr.HTML(),
                                 gr.File(label="Output",container=False,elem_classes="fileblock",visible=True)],
                        allow_flagging = 'never')
    return demo


if __name__ == "__main__":
    demo = create_app()
    demo.launch(server_name="localhost", server_port=7865)
