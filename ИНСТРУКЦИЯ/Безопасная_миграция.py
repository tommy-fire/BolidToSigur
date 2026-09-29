"""Windows/Tk desktop UI. SQL/IO in workers; Tk changes on the main thread only."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, queue, os, sys
from pathlib import Path
from safe_w34 import discover, snapshot, prepare, build, read_csv, write_csv, REVIEW


def main():
    root=tk.Tk();root.title('Болид → Sigur · сотрудники, фото и W34 · v3');root.geometry('1150x830')
    q=queue.Queue(); fields={}; buttons=[]
    state={'found':[],'auth':None,'path':None,'rows':[],'busy':False}
    top=ttk.LabelFrame(root,text='1. Найти базу — как раньше',padding=8);top.pack(fill='x',padx=10,pady=8)
    for i,(name,label,default) in enumerate([('user','Логин SQL (пусто = Windows)',''),('pwd','Пароль SQL',''),('server','Сервер (можно оставить пустым)',''),('out','Куда сохранить',str(Path.home()/'BolidExport'))]):
        ttk.Label(top,text=label).grid(row=i,column=0,sticky='w')
        v=tk.StringVar(value=default);fields[name]=v
        ttk.Entry(top,textvariable=v,show='*' if name=='pwd' else '',width=55).grid(row=i,column=1,sticky='ew',padx=6,pady=2)
    ttk.Label(top,text='Найденная база').grid(row=4,column=0,sticky='w')
    dbbox=ttk.Combobox(top,state='readonly',width=70);dbbox.grid(row=4,column=1,sticky='ew',padx=6)
    top.columnconfigure(1,weight=1)
    ttk.Label(top,text='Поиск использует службы SQL, реестр и резервные варианты подключения. Пароль не записывается в файлы.').grid(row=5,column=0,columnspan=3,sticky='w')
    def log(text):q.put(('log',text))
    def task(fn,on_done):
        if state['busy']:return
        state['busy']=True
        for b in buttons:b.configure(state='disabled')
        def worker():
            try:q.put(('done',(fn(),on_done)))
            except Exception as ex:q.put(('error',str(ex)))
        threading.Thread(target=worker,daemon=True).start()
    def button(parent,text,fn,**grid):
        b=ttk.Button(parent,text=text,command=fn);buttons.append(b)
        if grid:b.grid(**grid)
        else:b.pack(side='left',padx=3,pady=3)
        return b
    def find():
        user,pw,manual=fields['user'].get().strip(),fields['pwd'].get(),fields['server'].get().strip()
        state['found']=[];dbbox.set('');dbbox['values']=[]
        def done(found):
            state['found']=found;state['auth']=(user,pw,manual)
            dbbox['values']=[f"{x['server']} / {x['db']} ({x['people']} сотрудников)" for x in found]
            if len(found)==1:dbbox.current(0)
            if not found:messagebox.showwarning('База не найдена','Проверьте логин и пароль. При необходимости укажите сервер из настроек Ориона. .bak не нужен.')
            else:log('Поиск завершён. Подтвердите нужную базу в списке и нажмите «Выгрузить».')
        task(lambda:discover(user,pw,manual,log),done)
    def exported(path):
        state['path']=Path(path);reload_review();log('Готово. Исходные таблицы, кадровые данные и фотографии сохранены: '+str(Path(path).parent))
    def export():
        idx=dbbox.current()
        if idx<0 or idx>=len(state['found']):messagebox.showwarning('Найдите базу','Нажмите «НАЙТИ БАЗУ», затем выберите базу.');return
        if state['auth']!=(fields['user'].get().strip(),fields['pwd'].get(),fields['server'].get().strip()):
            messagebox.showwarning('Параметры изменены','Логин, пароль или сервер изменены. Повторите поиск.');return
        db=dict(state['found'][idx]);out=fields['out'].get()
        if not messagebox.askyesno('Подтвердите базу',f"Выгрузить только чтением?\n{db['server']} / {db['db']}\nЕсли есть несколько баз, убедитесь, что это рабочая."):return
        def work():
            log('Читаю исходные таблицы, справочники и фотографии...')
            folder=snapshot(db['server'],db['db'],db['user'],db['password'],out)
            return prepare(folder)
        task(work,exported)
    button(top,'НАЙТИ БАЗУ',find,row=0,column=2,padx=6)
    button(top,'ВЫГРУЗИТЬ',export,row=2,column=2,padx=6)
    def folder_pick():
        p=filedialog.askdirectory()
        if p:fields['out'].set(p)
    button(top,'Папка…',folder_pick,row=3,column=2,padx=6)

    mid=ttk.LabelFrame(root,text='2. Проверить W34 и разрешить нужные ключи',padding=6);mid.pack(fill='both',expand=True,padx=10)
    ttk.Label(mid,text='Таблица — по одному ключу в строке. Выделение нескольких строк: Ctrl/Shift. «Все» — Ctrl+A.\nПрофиль = группа одинакового способа чтения. Для автопереноса нужны 3 разных номера Sigur в этом профиле.').pack(anchor='w')
    frame=ttk.Frame(mid);frame.pack(fill='both',expand=True)
    cols=['ID','ФИО','Кандидат W34','Считано Sigur','Профиль','Разрешён','Ошибка']
    tree=ttk.Treeview(frame,columns=cols,show='headings',selectmode='extended',height=10)
    for k in cols:tree.heading(k,text=k);tree.column(k,width=110 if k!='ФИО' else 210)
    y=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=y.set)
    tree.pack(side='left',fill='both',expand=True);y.pack(side='right',fill='y')
    tree.bind('<Control-a>',lambda e:tree.selection_set(tree.get_children()))
    def reload_review():
        if state['path']:state['rows']=read_csv(state['path'])
        render()
        available=sorted({k for r in state['rows'] for k in __import__('json').loads(r.get('SourceMetadata') or '{}')})
        expiry_box['values']=['Не переносить автоматически']+available
    def render():
        selected=tree.selection();tree.delete(*tree.get_children())
        for i,r in enumerate(state['rows']):
            tree.insert('', 'end',iid=str(i),values=[r.get(k,'') for k in ['SourceKeyID','ФИО','CandidateW34','ObservedW34','Profile','Approve','DecodeError']])
        tree.selection_set([i for i in selected if tree.exists(i)])
    def save():
        if state['path']:write_csv(state['path'],state['rows'],REVIEW)
    def selected_rows():return [state['rows'][int(i)] for i in tree.selection()]
    controls=ttk.Frame(mid);controls.pack(fill='x')
    profile=tk.StringVar(value='Группа 1');ttk.Label(controls,text='Профиль:').pack(side='left');ttk.Entry(controls,textvariable=profile,width=17).pack(side='left')
    def set_profile():
        for r in selected_rows():r['Profile']=profile.get().strip()
        save();render()
    button(controls,'Задать выделенным',set_profile)
    observed=tk.StringVar();ttk.Label(controls,text='Номер из Sigur:').pack(side='left');ttk.Entry(controls,textvariable=observed,width=13).pack(side='left')
    def set_observed():
        rows=selected_rows()
        if len(rows)!=1:messagebox.showwarning('Одна карта','Выделите ровно одну строку ключа.');return
        import re
        value=observed.get().strip().upper()
        if value and not re.fullmatch('[0-9A-F]{8}',value):messagebox.showwarning('Формат W34','Ровно 8 HEX-знаков, включая нули.');return
        rows[0]['ObservedW34']=value;save();render()
    button(controls,'Сохранить номер',set_observed)
    more=ttk.Frame(mid);more.pack(fill='x')
    def approve(yes):
        rows=selected_rows()
        if not rows:return
        if yes and not messagebox.askyesno('Проверка разрешений',f'Выбрано ключей: {len(rows)}.\nВладельцы, действующие статусы и сроки проверены в Орионе?\nУволенные/заблокированные ключи нужно исключить. Права не копируются автоматически.'):return
        for r in rows:r['Approve']='ДА' if yes else ''
        save();render()
    button(more,'Разрешить выделенные',lambda:approve(True));button(more,'Исключить выделенные',lambda:approve(False))
    def open_saved():
        path=filedialog.askopenfilename(title='Проверка.csv рядом с pList.csv и pMark.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:state['path']=Path(path);reload_review()
            except Exception as ex:messagebox.showerror('Не удалось открыть',str(ex))
    button(more,'Открыть прежнюю выгрузку',open_saved)
    def open_folder():
        if state['path'] and sys.platform=='win32':os.startfile(state['path'].parent)
    button(more,'Папка выгрузки',open_folder)

    bottom=ttk.LabelFrame(root,text='3. Сформировать файлы для проверки и импорта',padding=6);bottom.pack(fill='x',padx=10,pady=6)
    ttk.Label(bottom,text='Поле окончания срока ключа (только если смысл подтверждён):').pack(side='left')
    expiry_box=ttk.Combobox(bottom,state='readonly',width=27,values=['Не переносить автоматически']);expiry_box.set('Не переносить автоматически');expiry_box.pack(side='left')
    def make():
        if not state['path']:messagebox.showwarning('Нет выгрузки','Сначала выгрузите базу или откройте Проверка.csv.');return
        save();path=state['path'];expiry=expiry_box.get();expiry='' if expiry=='Не переносить автоматически' else expiry
        if not messagebox.askyesno('Тестовый импорт','Сформировать файлы?\nБез выбранного поля срока конечные сроки не подставляются автоматически.\nНачало действия, расписания и исходные блокировки нужно настроить отдельно.\nНе выдавайте рабочие права до проверки ограничений.'):return
        def done(out):
            log('РЕЗУЛЬТАТ: '+str(out))
            messagebox.showinfo('Файлы подготовлены','Папка:\n'+str(out)+'\n\nОткройте Отчёт.json, Исключения.csv и Предупреждения_данных.csv. Сначала импортируйте 3–10 сотрудников в тестовую базу.')
        task(lambda:build(path,expiry),done)
    button(bottom,'СОЗДАТЬ ФАЙЛЫ',make)
    text=tk.Text(root,height=7,wrap='word');text.pack(fill='x',padx=10,pady=(0,8))
    def unlock():
        state['busy']=False
        for b in buttons:b.configure(state='normal')
    def poll():
        try:
            while True:
                kind,data=q.get_nowait()
                if kind=='log':text.insert('end',str(data)+'\n');text.see('end')
                elif kind=='error':
                    unlock();log('ОШИБКА: '+data);messagebox.showerror('Операция не завершена',data)
                else:
                    unlock();result,cb=data
                    try:cb(result)
                    except Exception as ex:messagebox.showerror('Ошибка обработки результата',str(ex))
        except queue.Empty:pass
        root.after(200,poll)
    def close():
        if not state['busy'] or messagebox.askyesno('Операция идёт','Прервать текущую операцию и закрыть программу?'):root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);poll();root.mainloop()

if __name__=='__main__':main()
