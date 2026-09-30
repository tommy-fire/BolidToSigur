"""Simple two-button workflow. No approvals, mapping guesses or SQL writes in UI."""
import importlib.util
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from safe_w34 import discover
from simple_flow import export_database, convert_file


def main():
    root=tk.Tk();root.title('Болид → Sigur');root.geometry('720x520');root.minsize(680,500)
    root.configure(padx=18,pady=15)
    home=Path(__file__).resolve().parent
    user=tk.StringVar();password=tk.StringVar();status=tk.StringVar(value='Введите логин и пароль либо сразу выберите ранее сохранённую выгрузку.')
    q=queue.Queue();state={'busy':False};buttons=[]
    ttk.Label(root,text='Болид → файл → Sigur',font=('Segoe UI',17,'bold')).pack(anchor='w')
    ttk.Label(root,text='Все файлы сохраняются рядом с программой:\n'+str(home),wraplength=670).pack(anchor='w',pady=(5,15))
    form=ttk.Frame(root);form.pack(fill='x')
    ttk.Label(form,text='Логин SQL').grid(row=0,column=0,sticky='w',pady=4)
    ttk.Entry(form,textvariable=user,width=40).grid(row=0,column=1,sticky='ew',padx=12)
    ttk.Label(form,text='Пароль SQL').grid(row=1,column=0,sticky='w',pady=4)
    ttk.Entry(form,textvariable=password,show='*',width=40).grid(row=1,column=1,sticky='ew',padx=12)
    form.columnconfigure(1,weight=1)
    ttk.Label(root,text='Для входа Windows оставьте логин пустым.').pack(anchor='w',pady=(4,12))
    def task(fn,done):
        if state['busy']:return
        state['busy']=True
        for b in buttons:b.configure(state='disabled')
        def work():
            try:q.put(('done',(fn(),done)))
            except Exception as ex:q.put(('error',str(ex)))
        threading.Thread(target=work,daemon=True).start()
    def open_folder(path):
        if sys.platform=='win32':os.startfile(str(path))
    def writable():
        probe=home/'.write_check'
        try:probe.write_text('ok');probe.unlink();return True
        except OSError:
            messagebox.showerror('Нет доступа к папке','Перенесите программу в папку с правом записи, например C:\\BolidToSigur, не в Program Files.');return False
    def export_one(db):
        status.set('Выгружаю сотрудников, карты и фото. Дождитесь окончания…')
        def done(file):
            status.set('Сохранено: '+file.name+'\nТеперь нажмите вторую кнопку и выберите этот файл.')
            messagebox.showinfo('Выгрузка готова','Сохранено рядом с программой:\n'+str(file)+'\n\nДля следующего шага нажмите кнопку 2.')
        task(lambda:export_database(db,home),done)
    def choose(found):
        if not found:status.set('База не найдена.');messagebox.showerror('База не найдена','Проверьте логин/пароль и доступ к SQL Server. Нужен Microsoft ODBC-драйвер.');return
        if len(found)==1:export_one(found[0]);return
        # Never silently choose a different database. This dialog appears only if ambiguous.
        win=tk.Toplevel(root);win.title('Найдено несколько баз');win.transient(root);win.grab_set();win.geometry('620x240')
        ttk.Label(win,text='Выберите рабочую базу Болид. Программа не может определить её по размеру.').pack(padx=10,pady=10)
        box=tk.Listbox(win,height=5)
        for db in found:box.insert('end',f"{db['server']} / {db['db']} ({db['people']} сотрудников)")
        box.pack(fill='both',expand=True,padx=10)
        def selected():
            if not box.curselection():return
            db=found[box.curselection()[0]];win.destroy();export_one(db)
        ttk.Button(win,text='Выгрузить эту базу',command=selected).pack(pady=8)
    def step_one():
        if not writable():return
        u=user.get().strip();pw=password.get();status.set('Ищу базу автоматически…')
        def work():
            if importlib.util.find_spec('pyodbc') is None:
                q.put(('status','Устанавливаю библиотеку SQL (нужен интернет)…'))
                subprocess.run([sys.executable,'-m','pip','install','pyodbc>=5.1,<6'],check=True,timeout=180)
            return discover(u,pw,log=lambda msg:q.put(('status',msg)))
        task(work,choose)
    def step_two():
        if not writable():return
        path=filedialog.askopenfilename(title='Выберите выгрузку из Болид',initialdir=home,filetypes=[('Выгрузка Болид','*.bolid')])
        if not path:return
        status.set('Готовлю файл для Sigur и отчёт. База Болид не требуется…')
        def done(result):
            out,report=result
            candidates=report.get('draft_candidates',0)
            count=report.get('cards_file',{}).get('people',0)
            status.set(f'Готово: {out.name}\nСотрудников: {count}. Кандидатов карт для сверки: {candidates}.')
            messagebox.showinfo('Файлы подготовлены',f'Результат: {out}\n\nСотрудников: {count}.\nНеподтверждённые номера карт — в отдельном отчёте, НЕ выданы как пропуска.\n\nФайл кадров для Sigur готовится без номеров карт до первой сверки реальных считываний. Прочитайте СНАЧАЛА_ПРОЧИТАТЬ.txt. Рабочую систему пока не переключайте.')
            open_folder(out)
        task(lambda:convert_file(path,home),done)
    for label,fn in [('1. Найти базу и выгрузить',step_one),('2. Выбрать выгрузку и создать файл Sigur',step_two)]:
        b=ttk.Button(root,text=label,command=fn);b.pack(fill='x',ipady=10,pady=5);buttons.append(b)
    ttk.Separator(root).pack(fill='x',pady=12)
    ttk.Label(root,textvariable=status,wraplength=665).pack(anchor='w')
    ttk.Label(root,text='Номера карт требуют первой проверки на считывателе. До неё XLS содержит только кадровые карточки; коды карт — в отчёте сверки. Права доступа программа не назначает.',wraplength=665,foreground='#844300').pack(anchor='w',pady=10)
    def poll():
        try:
            while True:
                kind,data=q.get_nowait()
                if kind=='status':status.set(data)
                else:
                    state['busy']=False
                    for b in buttons:b.configure(state='normal')
                    if kind=='error':status.set('Не получилось: '+data);messagebox.showerror('Операция не завершена',data)
                    else:
                        result,cb=data
                        try:cb(result)
                        except Exception as ex:status.set('Ошибка: '+str(ex));messagebox.showerror('Не завершено',str(ex))
        except queue.Empty:pass
        root.after(120,poll)
    def close():
        if state['busy']:messagebox.showinfo('Подождите','Идёт операция. Дождитесь окончания, чтобы не получить неполную выгрузку.');return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);poll();root.mainloop()

if __name__=='__main__':main()
