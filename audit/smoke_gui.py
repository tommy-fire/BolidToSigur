"""Run: xvfb-run -a python audit/smoke_gui.py
Real Tk event loop, mocked dialogs, synthetic offline file. No SQL/Sigur access.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ИНСТРУКЦИЯ'))
import Проверка_специалиста as ui
import test_bundle
import safe_w34 as s
import transfer_bundle as b


def children(w):
    result=[]
    for c in w.winfo_children():result.append(c);result+=children(c)
    return result


def run(source_mode=False):
    with tempfile.TemporaryDirectory() as td:
        base=Path(td);src=base/'src';src.mkdir();review=test_bundle.fixture(src)
        marks=s.read_csv(src/'pMark.csv');marks[0].update(Start='2020-01-02',Finish='2030-01-02')
        s.write_csv(src/'pMark.csv',marks,list(marks[0]));package=b.pack(src,base/'input.bolid')
        saved=base/'reviewed.bolid';errors=[];messages=[];progress={'step':0};deadline=time.monotonic()+12
        original_loop=tk.Tk.mainloop
        def loop(root,*args,**kwargs):
            def stop():
                for token in root.tk.call('after','info'):root.after_cancel(token)
                root.destroy()
            def tick():
                try:
                    if errors:raise AssertionError(errors)
                    if time.monotonic()>deadline:raise AssertionError('GUI timed out: '+str(progress))
                    widgets=children(root)
                    def btn(label):return next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')==label)
                    tree=next(w for w in widgets if isinstance(w,ttk.Treeview))
                    step=progress['step']
                    if step==0:
                        entries=[w for w in widgets if type(w) is ttk.Entry]
                        entries[3].delete(0,'end');entries[3].insert(0,str(base/'work'))
                        if source_mode:
                            btn('НАЙТИ БАЗУ').invoke();progress['step']=10
                        else:
                            btn('ОТКРЫТЬ ФАЙЛ .bolid').invoke();progress['step']=1
                    elif step==10 and str(btn('НАЙТИ БАЗУ').cget('state'))=='normal':
                        review.unlink()
                        btn('ВЫГРУЗИТЬ → СОХРАНИТЬ .bolid').invoke();progress['step']=1
                    elif step==1 and tree.get_children() and str(btn('ОТКРЫТЬ ФАЙЛ .bolid').cget('state'))=='normal':
                        assert len(tree.get_children())==1
                        tree.selection_set('0')
                        entries=[w for w in widgets if type(w) is ttk.Entry]
                        entries[-1].delete(0,'end');entries[-1].insert(0,tree.item('0','values')[3])
                        btn('Сохранить номер').invoke();btn('Разрешить выделенные').invoke()
                        assert tree.item('0','values')[6]=='ДА'
                        combos=[w for w in widgets if isinstance(w,ttk.Combobox) and 'Start' in w.cget('values')]
                        assert len(combos)==2;combos[0].set('Start');combos[1].set('Finish')
                        btn('Сохранить проверку в .bolid').invoke();progress['step']=2
                    elif step==2 and saved.exists() and str(btn('СОЗДАТЬ XLS ДЛЯ SIGUR').cget('state'))=='normal':
                        btn('СОЗДАТЬ XLS ДЛЯ SIGUR').invoke();progress['step']=3
                    elif step==3 and any(t=='XLS сформирован' for t,_ in messages):
                        files=list(base.glob('**/result_*/ТЕСТ_Импорт_Sigur.xls'));assert len(files)==1
                        check=b.unpack(saved,base/'check');r=s.read_csv(check)[0];assert r['Approve']=='ДА' and r['ObservedW34']==r['CandidateW34']
                        st=json.loads((check.parent/'transfer_settings.json').read_text());assert st['start_column']=='Start' and st['expiry_column']=='Finish'
                        for size in ('1180x820','880x680'):
                            root.geometry(size);root.update_idletasks()
                            target=btn('СОЗДАТЬ XLS ДЛЯ SIGUR')
                            assert target.winfo_rooty()+target.winfo_height()<=root.winfo_rooty()+root.winfo_height()
                        progress['step']=4;stop();return
                    root.after(30,tick)
                except Exception as ex:errors.append(repr(ex));stop()
            root.after(30,tick);original_loop(root,*args,**kwargs)
        with patch.object(tk.Tk,'mainloop',loop),patch.object(ui.filedialog,'askopenfilename',return_value=str(package)),patch.object(ui.filedialog,'asksaveasfilename',side_effect=[str(base/'new.bolid'),str(saved)] if source_mode else [str(saved)]),patch.object(ui.messagebox,'askyesno',return_value=True),patch.object(ui.messagebox,'showinfo',side_effect=lambda t,m:messages.append((t,m))),patch.object(ui.messagebox,'showerror',side_effect=lambda t,m:errors.append((t,m))),patch.object(s,'load_exporter',side_effect=AssertionError('SQL loaded during offline flow')):
            if source_mode:
                with patch.object(ui,'discover',return_value=[{'server':'mock','db':'synthetic','people':1,'user':None,'password':None}]),patch.object(ui,'snapshot',return_value=src),patch.object(ui.importlib.util,'find_spec',return_value=object()):ui.main()
            else:ui.main()
        assert not errors,errors
        assert progress['step']==4,progress
        print(('SOURCE SQL MOCKS: ' if source_mode else 'OFFLINE: ')+'PASS: real Tk GUI open .bolid -> edit observed number -> approve -> select both dates -> save .bolid -> create XLS; no SQL; 1180x820 and 880x680 controls visible.')

if __name__=='__main__':
    run()
    run(source_mode=True)
