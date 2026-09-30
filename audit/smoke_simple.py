"""Simple UI smoke: real Tk + synthetic SQL export; no hardware/live SQL."""
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ИНСТРУКЦИЯ'))
import Безопасная_миграция as ui
import simple_flow as flow
import safe_w34 as s
import test_bundle
from smoke_gui import children


def run():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);src=root/'source';src.mkdir();path=test_bundle.fixture(src);path.unlink()
        app=root/'app';app.mkdir();notices=[];errors=[];step={'n':0};deadline=time.monotonic()+10
        original=tk.Tk.mainloop
        def loop(window,*args,**kwargs):
            def finish():
                for token in window.tk.call('after','info'):window.after_cancel(token)
                window.destroy()
            def tick():
                try:
                    if time.monotonic()>deadline:raise AssertionError('timeout')
                    widgets=children(window);buttons=[w for w in widgets if isinstance(w,ttk.Button)]
                    assert len(buttons)==2
                    assert not any(isinstance(w,(ttk.Checkbutton,ttk.Notebook,ttk.Treeview,ttk.Combobox)) for w in widgets)
                    if step['n']==0:buttons[0].invoke();step['n']=1
                    elif step['n']==1 and notices:
                        packages=list(app.glob('*.bolid'));assert len(packages)==1
                        buttons[1].invoke();step['n']=2
                    elif step['n']==2 and len(notices)>=2:
                        outputs=list(app.glob('Для_Sigur_*'));assert len(outputs)==1
                        report=json.loads((outputs[0]/'Отчёт.json').read_text())
                        assert report['trial_import'] and report['hardware_verified'] is False
                        assert (outputs[0]/'ПРОБНЫЙ_ПОЛНЫЙ_Импорт_Sigur.xls').exists()
                        import xlrd
                        sh=xlrd.open_workbook(outputs[0]/report['cards_filename']).sheet_by_index(0)
                        assert sh.cell_value(1,sh.row_values(0).index('Номер пропуска'))=='12340001'
                        assert 'Тип пропуска' not in sh.row_values(0)
                        assert report['trial_cards']==1
                        window.geometry('680x500');window.update_idletasks()
                        assert buttons[1].winfo_rooty()+buttons[1].winfo_height()<window.winfo_rooty()+500
                        step['n']=3;finish();return
                    window.after(25,tick)
                except Exception as ex:errors.append(str(ex));finish()
            window.after(25,tick);original(window,*args,**kwargs)
        with patch.object(ui,'__file__',str(app/'Безопасная_миграция.py')),patch.object(ui,'discover',return_value=[{'server':'mock','db':'mock'}]),patch.object(ui.importlib.util,'find_spec',return_value=object()),patch.object(flow,'snapshot',return_value=src),patch.object(ui.filedialog,'askopenfilename',side_effect=lambda **kw:str(next(app.glob('*.bolid')))),patch.object(ui.messagebox,'showinfo',side_effect=lambda *a:notices.append(a)),patch.object(ui.messagebox,'showerror',side_effect=lambda *a:errors.append(a)),patch.object(tk.Tk,'mainloop',loop):
            ui.main()
        assert step['n']==3 and not errors,(step,errors)
        print('PASS: simple Tk, exactly 2 buttons, no tabs/checkboxes; mocked discovery/export -> .bolid beside app -> select file -> full trial XLS with a candidate card, no pass-type column, and diagnostic reports. Linux/Xvfb only; no live SQL/Sigur.')

if __name__=='__main__':run()
