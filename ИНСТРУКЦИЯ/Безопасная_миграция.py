"""Two-stage Tk UI. SQL is used only in stage 1; stage 2 opens portable files."""
import datetime
import importlib.util
import subprocess
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from safe_w34 import discover, snapshot, prepare, build, read_csv, write_csv, REVIEW, decode
from transfer_bundle import pack, unpack, validate_snapshot

NO_FIELD='Не переносить автоматически'


def main():
    root=tk.Tk();root.title('Болид → файл → Sigur · v3.2');root.geometry('1180x820');root.minsize(880,680)
    q=queue.Queue();buttons=[];fields={}
    state={'found':[],'auth':None,'path':None,'rows':[],'busy':False,'result':None}
    ttk.Label(root,text='Болид → один файл .bolid → XLS для Sigur',font=('Segoe UI',15,'bold')).pack(anchor='w',padx=12,pady=(10,4))
    tabs=ttk.Notebook(root);tabs.pack(fill='both',expand=True,padx=10,pady=4)
    source_tab=ttk.Frame(tabs,padding=10);target_tab=ttk.Frame(tabs,padding=8)
    tabs.add(source_tab,text='1. Получить файл из Болид');tabs.add(target_tab,text='2. Открыть файл → подготовить Sigur')
    current=tk.StringVar(value='Файл не открыт. Сначала выгрузите базу или откройте .bolid на второй вкладке.')
    ttk.Label(root,textvariable=current,wraplength=1150).pack(fill='x',padx=12)
    text=tk.Text(root,height=4,wrap='word',state='disabled');text.pack(fill='x',padx=10,pady=(4,8))

    def log(msg):q.put(('log',str(msg)))
    def button(parent,label,fn,**grid):
        b=ttk.Button(parent,text=label,command=fn);buttons.append(b)
        if grid:b.grid(**grid)
        else:b.pack(side='left',padx=3,pady=3)
        return b
    def task(fn,done):
        if state['busy']:return
        state['busy']=True
        for b in buttons:b.configure(state='disabled')
        def worker():
            try:q.put(('done',(fn(),done)))
            except Exception as ex:q.put(('error',str(ex)))
        threading.Thread(target=worker,daemon=True).start()
    def unlock():
        state['busy']=False
        for b in buttons:b.configure(state='normal')
    def poll():
        try:
            while True:
                kind,data=q.get_nowait()
                if kind=='log':
                    text.configure(state='normal');text.insert('end',data+'\n');text.see('end');text.configure(state='disabled')
                elif kind=='error':
                    unlock();log('ОШИБКА: '+data);messagebox.showerror('Не завершено',data)
                else:
                    unlock();result,cb=data
                    try:cb(result)
                    except Exception as ex:messagebox.showerror('Не удалось обработать результат',str(ex))
        except queue.Empty:pass
        root.after(150,poll)
    def open_dir(path):
        if sys.platform=='win32':os.startfile(str(path))
        else:messagebox.showinfo('Папка',str(path))

    ttk.Label(source_tab,text='Этот шаг выполняется на компьютере с доступом к базе Болид.\nВ файл попадут сотрудники, исходные коды всех карт, справочники и доступные фото. SQL только читается.',wraplength=1000).pack(anchor='w',pady=(0,12))
    top=ttk.LabelFrame(source_tab,text='Прежний автопоиск базы',padding=12);top.pack(fill='x')
    for i,(key,label,default) in enumerate([
        ('user','Логин SQL (пусто = Windows)',''),('pwd','Пароль SQL',''),
        ('server','Сервер (необязательно)',''),('out','Рабочие папки',str(Path.home()/'BolidExport'))]):
        ttk.Label(top,text=label).grid(row=i,column=0,sticky='w',pady=4)
        fields[key]=tk.StringVar(value=default)
        ttk.Entry(top,textvariable=fields[key],show='*' if key=='pwd' else '',width=55).grid(row=i,column=1,sticky='ew',padx=8,pady=4)
    top.columnconfigure(1,weight=1)
    dbbox=ttk.Combobox(top,state='readonly',width=65)
    ttk.Label(top,text='Рабочая база').grid(row=4,column=0,sticky='w');dbbox.grid(row=4,column=1,sticky='ew',padx=8,pady=4)
    def find():
        user,pw,server=(fields[k].get() for k in ('user','pwd','server'));user=user.strip();server=server.strip()
        state['found']=[];dbbox.set('');dbbox['values']=[]
        def done(found):
            state['found']=found;state['auth']=(user,pw,server)
            dbbox['values']=[f"{r['server']} / {r['db']} ({r['people']} сотрудников)" for r in found]
            if len(found)==1:dbbox.current(0)
            if not found:messagebox.showwarning('База не найдена','Проверьте логин/пароль. При необходимости укажите сервер из настроек Ориона.')
            else:log('Выберите именно рабочую базу и сохраните файл .bolid.')
        install=importlib.util.find_spec('pyodbc') is None
        if install and not messagebox.askyesno('Библиотека SQL','Для поиска базы нужна библиотека pyodbc. Установить её сейчас через pip? Нужен интернет. Microsoft ODBC-драйвер устанавливается отдельно. Для открытия .bolid это не требуется.'):return
        def work():
            if install:
                log('Устанавливаю pyodbc для подключения к SQL…')
                subprocess.run([sys.executable,'-m','pip','install','pyodbc>=5.1,<6'],check=True,timeout=180)
            return discover(user,pw,server,log)
        task(work,done)
    button(top,'НАЙТИ БАЗУ',find,row=0,column=2,padx=4)
    def choose_work():
        path=filedialog.askdirectory(title='Где хранить рабочие копии и результаты')
        if path:fields['out'].set(path)
    button(top,'Папка…',choose_work,row=3,column=2,padx=4)
    def ask_bundle(title,initial=''):
        return filedialog.asksaveasfilename(title=title,defaultextension='.bolid',initialfile=initial or ('Болид_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.bolid'),filetypes=[('Файл выгрузки Болид','*.bolid')])
    def export():
        idx=dbbox.current()
        if idx<0 or idx>=len(state['found']):messagebox.showwarning('Нет базы','Найдите и выберите рабочую базу.');return
        auth=(fields['user'].get().strip(),fields['pwd'].get(),fields['server'].get().strip())
        if auth!=state['auth']:messagebox.showwarning('Параметры изменились','Повторите поиск после изменения логина/пароля/сервера.');return
        dest=ask_bundle('Сохранить один файл выгрузки из Болид')
        if not dest:return
        save()
        db=dict(state['found'][idx]);out=fields['out'].get()
        if not messagebox.askyesno('Подтвердите базу',f"Выгрузить только чтением?\n{db['server']} / {db['db']}\nПароль подключения в файл не записывается."):return
        def work():
            log('Читаю таблицы, справочники и фото…')
            folder=snapshot(db['server'],db['db'],db['user'],db['password'],out)
            review=prepare(folder)
            log('Сохраняю переносимый файл .bolid…')
            pack(folder,dest)
            return review,dest
        def done(result):
            review,bundle=result;activate(review)
            log('СОХРАНЁН ФАЙЛ: '+str(bundle))
            messagebox.showinfo('Выгрузка сохранена',str(bundle)+'\n\nМожно закрыть программу и позже открыть этот файл на вкладке 2 — на этом или другом ПК.\nСейчас данные уже открыты на вкладке 2. Для сохранения последующих правок используйте «Сохранить проверку в .bolid».')
        task(work,done)
    source_actions=ttk.Frame(source_tab);source_actions.pack(fill='x',pady=12)
    button(source_actions,'ВЫГРУЗИТЬ → СОХРАНИТЬ .bolid',export)
    button(source_actions,'У меня уже есть файл →',lambda:tabs.select(target_tab))
    ttk.Label(source_tab,text='Файл .bolid — контейнер нашей программы, не резервная копия SQL и не файл импорта Sigur.\nЕго не нужно распаковывать вручную. На другой компьютер достаточно перенести этот файл и папку программы.\nФайл содержит персональные данные и номера карт. Он НЕ зашифрован — храните его в защищённом месте.',wraplength=1000).pack(anchor='w',pady=12)

    # Stage 2 is independent of SQL; read-only access to the archive, edits in a new work directory.
    loadbar=ttk.Frame(target_tab);loadbar.pack(fill='x')
    ttk.Label(target_tab,text='Подключение к Болид для этого шага не нужно. Отображаемый кандидат номера ещё не подтверждает проход карты.',wraplength=1100).pack(anchor='w')
    summary=tk.StringVar(value='Откройте файл .bolid. Для старой рабочей папки можно выбрать Проверка.csv.')
    ttk.Label(target_tab,textvariable=summary).pack(anchor='w',pady=4)
    frame=ttk.Frame(target_tab);frame.pack(fill='both',expand=True)
    cols=[('SourceKeyID','ID ключа',75),('ФИО','ФИО',210),('RawCodeP','Исходный CodeP',230),('CandidateW34','Кандидат W34',120),('ObservedW34','Считано Sigur',120),('Profile','Профиль',110),('Approve','Разрешён',75),('DecodeError','Ошибка',240)]
    tree=ttk.Treeview(frame,columns=[k for k,_,_ in cols],show='headings',selectmode='extended',height=7)
    for key,label,width in cols:tree.heading(key,text=label);tree.column(key,width=width,minwidth=60,stretch=False)
    y=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);x=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
    tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
    tree.bind('<Control-a>',lambda e:tree.selection_set(tree.get_children()))
    def render():
        selected=tree.selection();tree.delete(*tree.get_children())
        for i,r in enumerate(state['rows']):tree.insert('', 'end',iid=str(i),values=[r.get(k,'') for k,_,_ in cols])
        tree.selection_set([i for i in selected if tree.exists(i)])
        errors=sum(bool(r.get('DecodeError')) for r in state['rows'])
        approved=sum(r.get('Approve','').upper()=='ДА' for r in state['rows'])
        summary.set(f"Ключей: {len(state['rows'])} • Разрешено оператором: {approved} • Ошибок исходного разбора: {errors}. Ctrl/Shift — несколько строк; двойной щелчок — исходные данные.")
    def settings():
        return {'start_column':'' if start_box.get()==NO_FIELD else start_box.get(),'expiry_column':'' if expiry_box.get()==NO_FIELD else expiry_box.get(),'personal_mode':'notes' if notes_only.get() else 'fields'}
    def save():
        if state['path']:
            write_csv(state['path'],state['rows'],REVIEW)
            p=state['path'].parent/'transfer_settings.json';tmp=p.with_suffix('.tmp')
            tmp.write_text(json.dumps(settings(),ensure_ascii=False),encoding='utf-8');os.replace(tmp,p)
    def activate(path):
        path=Path(path)
        validate_snapshot(path.parent)
        rows=read_csv(path)
        marks=read_csv(path.parent/'pMark.csv');available=sorted({k for r in marks for k in r})
        st={};p=path.parent/'transfer_settings.json'
        if p.exists():st=json.loads(p.read_text(encoding='utf-8'))
        mark_by_id={str(m.get('ID',m.get('id',''))):m for m in marks}
        for r in rows:
            if r['SourceKeyID'] in mark_by_id:r['SourceMetadata']=json.dumps(mark_by_id[r['SourceKeyID']],ensure_ascii=False)
            try:r['ABD'],r['CandidateW34']=decode(r['RawCodeP']);r['DecodeError']=''
            except ValueError as ex:r['ABD']='';r['CandidateW34']='';r['DecodeError']=str(ex)
        state.update(path=path,rows=rows,result=None)
        for box,key in [(start_box,'start_column'),(expiry_box,'expiry_column')]:
            box['values']=[NO_FIELD]+available
            selected=st.get(key,'');box.set(selected if selected in available else NO_FIELD)
        notes_only.set(st.get('personal_mode')=='notes');experimental.set(False)
        current.set('Рабочая копия: '+str(path.parent));render();tabs.select(target_tab)
    def open_saved():
        selected=filedialog.askopenfilename(title='Открыть выгрузку .bolid или прежнюю Проверка.csv',filetypes=[('Файл Болид','*.bolid'),('Прежняя проверка CSV','*.csv')])
        if not selected:return
        if Path(selected).suffix.lower()=='.bolid' and not messagebox.askyesno('Файл с персональными данными','Открывайте только свою выгрузку или файл от доверенного оператора. Файл может содержать уже одобренные ключи и контрольные номера. Проверка целостности не подтверждает автора файла. Продолжить?'):return
        save();out=fields['out'].get()
        def work():
            path=Path(selected)
            if path.suffix.lower()=='.bolid':return unpack(path,out)
            if path.name!='Проверка.csv':raise ValueError('Для прежней папки выберите Проверка.csv рядом с pList.csv/pMark.csv. Произвольный CSV не поддерживается.')
            validate_snapshot(path.parent);return path
        task(work,activate)
    def save_bundle():
        if not state['path']:messagebox.showwarning('Нет файла','Сначала откройте или выгрузите файл.');return
        dest=ask_bundle('Сохранить проверку вместе со всеми данными в один файл')
        if not dest:return
        save();folder=state['path'].parent;st=settings()
        task(lambda:pack(folder,dest,st),lambda p:(log('ПРОВЕРКА СОХРАНЕНА: '+str(p)),messagebox.showinfo('Сохранено',str(p)+'\nКонтрольные номера, разрешения и выбранные поля сроков сохранены. Диагностическая галочка не переносится.')))
    button(loadbar,'ОТКРЫТЬ ФАЙЛ .bolid',open_saved)
    button(loadbar,'Сохранить проверку в .bolid',save_bundle)
    button(loadbar,'Рабочая папка',lambda:open_dir(state['path'].parent) if state['path'] else None)
    def selected_rows():return [state['rows'][int(i)] for i in tree.selection()]
    def details(event=None):
        rows=selected_rows()
        if len(rows)!=1:return
        r=rows[0];win=tk.Toplevel(root);win.title('Исходные данные карты — без изменений');win.geometry('800x500')
        body=tk.Text(win,wrap='word');body.pack(fill='both',expand=True)
        lines=[f'{k}: {v}' for k,v in r.items() if k!='SourceMetadata']
        lines+=['\nИсходные поля записи ключа:',json.dumps(json.loads(r.get('SourceMetadata') or '{}'),ensure_ascii=False,indent=2)]
        body.insert('1.0','\n'.join(lines));body.configure(state='disabled')
    tree.bind('<Double-1>',details)
    controls=ttk.Frame(target_tab);controls.pack(fill='x',pady=(4,0))
    profile=tk.StringVar(value='Группа 1');observed=tk.StringVar()
    ttk.Label(controls,text='Профиль:').pack(side='left');ttk.Entry(controls,textvariable=profile,width=16).pack(side='left')
    def set_profile():
        for r in selected_rows():r['Profile']=profile.get().strip()
        save();render()
    button(controls,'Задать выделенным',set_profile)
    ttk.Label(controls,text='Номер из Sigur:').pack(side='left');ttk.Entry(controls,textvariable=observed,width=12).pack(side='left')
    def set_observed():
        rows=selected_rows();v=observed.get().strip().upper()
        if len(rows)!=1:messagebox.showwarning('Одна карта','Выделите ровно одну строку.');return
        if v and not re.fullmatch('[0-9A-F]{8}',v):messagebox.showwarning('W34','Ровно 8 HEX-знаков, включая нули.');return
        rows[0]['ObservedW34']=v;save();render()
    button(controls,'Сохранить номер',set_observed)
    approvals=ttk.Frame(target_tab);approvals.pack(fill='x')
    def approve(yes):
        rows=selected_rows()
        if not rows:return
        if yes and not messagebox.askyesno('Проверка',f'Ключей: {len(rows)}. Владельцы, статусы и сроки проверены в Болид?\nУволенные/заблокированные карты не разрешайте. Автопрофиль требует 3 разных реальных контрольных номера.'):return
        for r in rows:r['Approve']='ДА' if yes else ''
        save();render()
    button(approvals,'Разрешить выделенные',lambda:approve(True));button(approvals,'Исключить выделенные',lambda:approve(False))
    button(approvals,'Данные выбранной карты',details)
    dates=ttk.LabelFrame(target_tab,text='Сроки — выберите именно исходные поля карты, не сотрудника',padding=4);dates.pack(fill='x',pady=4)
    ttk.Label(dates,text='Начало:').grid(row=0,column=0);start_box=ttk.Combobox(dates,state='readonly',width=30,values=[NO_FIELD]);start_box.set(NO_FIELD);start_box.grid(row=0,column=1,padx=4,sticky='ew')
    ttk.Label(dates,text='Окончание:').grid(row=0,column=2);expiry_box=ttk.Combobox(dates,state='readonly',width=30,values=[NO_FIELD]);expiry_box.set(NO_FIELD);expiry_box.grid(row=0,column=3,padx=4,sticky='ew')
    dates.columnconfigure(1,weight=1);dates.columnconfigure(3,weight=1)
    notes_only=tk.BooleanVar(value=False);experimental=tk.BooleanVar(value=False)
    ttk.Checkbutton(target_tab,text='Дата рождения / паспорт / прописка — в Примечание вместо отдельных полей',variable=notes_only).pack(anchor='w')
    ttk.Checkbutton(target_tab,text='ДИАГНОСТИКА: несколько карт со сроками — только для пустой тестовой базы',variable=experimental).pack(anchor='w')
    outputbar=ttk.Frame(target_tab);outputbar.pack(fill='x',pady=(4,0))
    def make():
        if not state['path']:messagebox.showwarning('Нет файла','Откройте .bolid или получите его на первой вкладке.');return
        save();path=state['path'];st=settings();multi=experimental.get()
        if not messagebox.askyesno('Только тестовый импорт','Создать XLS для пустой тестовой базы Sigur?\nПервый тест: 3–10 сотрудников. Права «Турникет — 24/7» назначаются отдельно, без комнаты охраны.\nВ рабочую базу автоматически ничего не записывается.'):return
        if not st['start_column'] or not st['expiry_column']:
            if not messagebox.askyesno('Не выбраны обе даты','Одна или обе границы НЕ будут взяты из исходных полей. Sigur может заменить начало временем импорта, окончание считать бессрочным. Продолжить только для диагностики?'):return
        if multi and not messagebox.askyesno('Диагностика нескольких карт','Поддержка обеих дат второй и следующих карт требует проверки в Sigur. Файл будет помечен «НЕ ДЛЯ РАБОТЫ». Продолжить в пустой тестовой базе?'):return
        def done(out):
            state['result']=out;report=json.loads((out/'Отчёт.json').read_text(encoding='utf-8'))
            log('РЕЗУЛЬТАТ: '+str(out))
            messagebox.showinfo('XLS сформирован',f"Ключей принято: {report['accepted']}; исключено: {report['excluded']}.\n{out}\n\nПроверьте отчёт и причины исключений. XLS импортируется в самом Sigur: Персонал → Импорт из Excel.\nНе переносите XLS отдельно от папки фотографий.")
        task(lambda:build(path,st['expiry_column'],st['start_column'],st['personal_mode'],multi),done)
    button(outputbar,'СОЗДАТЬ XLS ДЛЯ SIGUR',make)
    button(outputbar,'Открыть папку результата',lambda:open_dir(state['result']) if state['result'] else messagebox.showinfo('Нет результата','Сначала создайте XLS.'))
    def close():
        if state['busy']:
            if not messagebox.askyesno('Операция идёт','Прервать операцию? Незавершённые файлы нельзя использовать.'):return
        else:
            try:save()
            except Exception as ex:
                messagebox.showerror('Не удалось сохранить рабочую копию',str(ex));return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);poll();root.mainloop()

if __name__=='__main__':main()
