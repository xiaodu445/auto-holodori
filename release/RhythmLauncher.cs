using System;
using System.IO;
using System.IO.Compression;
using System.Diagnostics;
using System.Drawing;
using System.Security.Cryptography;
using System.Threading;
using System.Windows.Forms;
using System.Runtime.InteropServices;
class Launcher {
    [DllImport("kernel32.dll")] static extern uint SetErrorMode(uint mode);
    const string PayloadSha="__PAYLOAD_SHA__";
    static string Hex(byte[] data) {return BitConverter.ToString(data).Replace("-", "").ToLowerInvariant();}
    [STAThread] static int Main(string[] args) {
        SetErrorMode(0x8003); // Child loader failures go to logs, never system-modal dialogs.
        bool test=Array.IndexOf(args,"--self-test")>=0;
        string cacheRoot=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"JumpRopeAssistant","cache");
        for(int i=0;i<args.Length-1;i++)if(args[i]=="--cache-root")cacheRoot=Path.GetFullPath(args[i+1]);
        string target=Path.Combine(cacheRoot,PayloadSha.Substring(0,16));
        Form form=null;ProgressBar bar=null;Label label=null;
        try {
            if(!test) {
                Application.EnableVisualStyles();form=new Form {Text="跳绳助手 · 首次准备",ClientSize=new Size(520,140),StartPosition=FormStartPosition.CenterScreen,FormBorderStyle=FormBorderStyle.FixedDialog,MaximizeBox=false,ControlBox=false};
                form.Icon=Icon.ExtractAssociatedIcon(System.Reflection.Assembly.GetExecutingAssembly().Location);
                label=new Label {Text="正在准备独立运行环境…",Location=new Point(20,20),Size=new Size(480,45)};
                bar=new ProgressBar {Location=new Point(20,80),Size=new Size(480,24)};form.Controls.Add(label);form.Controls.Add(bar);form.Show();Application.DoEvents();
            }
            Directory.CreateDirectory(cacheRoot);
            using(var mutex=new Mutex(false,"Local\\JumpRopeRelease-"+PayloadSha.Substring(0,16))) {
                bool locked=false;
                try {
                    while(!locked) {try {locked=mutex.WaitOne(100);} catch(AbandonedMutexException) {locked=true;} if(form!=null)Application.DoEvents();}
                    if(!File.Exists(Path.Combine(target,".ready"))) {
                        string staging=Path.GetFullPath(Path.Combine(cacheRoot,"partial-"+Guid.NewGuid().ToString("N")));
                        if(!staging.StartsWith(Path.GetFullPath(cacheRoot)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("Invalid cache directory");
                        Directory.CreateDirectory(staging);
                        string self=System.Reflection.Assembly.GetExecutingAssembly().Location;
                        using(var file=File.OpenRead(self)) {
                            file.Seek(-16,SeekOrigin.End);var footer=new byte[16];file.Read(footer,0,16);
                            if(System.Text.Encoding.ASCII.GetString(footer,8,8)!="JROPE001")throw new Exception("发布包不完整，请重新下载。");
                            long length=BitConverter.ToInt64(footer,0);long offset=file.Length-16-length;
                            if(offset<0)throw new Exception("发布包长度无效。");
                            using(var bounded=new Slice(file,offset,length)) {
                                using(var hash=SHA256.Create())if(Hex(hash.ComputeHash(bounded))!=PayloadSha)throw new Exception("发布包校验失败，请重新下载。");
                                bounded.Position=0;
                                using(var archive=new ZipArchive(bounded,ZipArchiveMode.Read)) {
                                    long total=0,done=0;foreach(var entry in archive.Entries)total+=entry.Length;
                                    foreach(var entry in archive.Entries) {
                                        string path=Path.GetFullPath(Path.Combine(staging,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                                        if(!path.StartsWith(staging+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("Unsafe archive path");
                                        if(entry.FullName.EndsWith("/")){Directory.CreateDirectory(path);continue;}
                                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                                        using(var input=entry.Open())using(var output=File.Create(path)) {
                                            byte[] buffer=new byte[1024*1024];int count;
                                            while((count=input.Read(buffer,0,buffer.Length))>0) {
                                                output.Write(buffer,0,count);done+=count;
                                                if(form!=null){bar.Value=(int)(done*95/Math.Max(1,total));label.Text="首次解压运行组件："+(done/1000000)+" / "+(total/1000000)+" MB";Application.DoEvents();}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        if(form!=null){label.Text="正在校验运行组件…";Application.DoEvents();}
                        foreach(string line in File.ReadAllLines(Path.Combine(staging,"MANIFEST.sha256"))) {
                            if(line.Length<67)continue;string path=Path.GetFullPath(Path.Combine(staging,line.Substring(66).Replace('/',Path.DirectorySeparatorChar)));
                            if(!path.StartsWith(staging+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("Invalid manifest path");
                            using(var file=File.OpenRead(path))using(var sha=SHA256.Create())if(Hex(sha.ComputeHash(file))!=line.Substring(0,64))throw new Exception("组件校验失败："+Path.GetFileName(path));
                        }
                        File.WriteAllText(Path.Combine(staging,".ready"),PayloadSha);
                        if(Directory.Exists(target))target=Path.Combine(cacheRoot,PayloadSha.Substring(0,16)+"-"+Guid.NewGuid().ToString("N"));
                        // Both resolved paths were checked within the dedicated cache root before this recursive move.
                        if(!Path.GetFullPath(target).StartsWith(Path.GetFullPath(cacheRoot)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("Invalid target path");
                        Directory.Move(staging,target);
                    }
                } finally {if(locked)mutex.ReleaseMutex();}
            }
            if(form!=null){bar.Value=100;label.Text="准备完成，正在打开中文界面…";Application.DoEvents();}
            var start=new ProcessStartInfo {FileName=Path.Combine(target,"runtime",test?"python.exe":"pythonw.exe"),Arguments="-X utf8 \""+Path.Combine(target,"bootstrap.py")+"\""+(test?" --self-test":""),WorkingDirectory=target,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden};
            // Do not inherit a developer Python/Conda installation or DLL PATH.
            var environmentKeys=new System.Collections.Generic.List<string>();
            foreach(string key in start.EnvironmentVariables.Keys)environmentKeys.Add(key);
            foreach(string key in environmentKeys) {
                string upper=key.ToUpperInvariant();
                if(upper.StartsWith("PYTHON")||upper.StartsWith("CONDA")||upper=="VIRTUAL_ENV")start.EnvironmentVariables.Remove(key);
            }
            start.EnvironmentVariables["PATH"]=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),"System32");
            if(test){start.RedirectStandardOutput=true;start.RedirectStandardError=true;}
            var process=Process.Start(start);
            if(test){string output=process.StandardOutput.ReadToEnd();string error=process.StandardError.ReadToEnd();process.WaitForExit();File.WriteAllText(Path.Combine(cacheRoot,"self-test.txt"),output+error);return process.ExitCode;}
            return 0;
        } catch(Exception e) {
            try{Directory.CreateDirectory(cacheRoot);File.WriteAllText(Path.Combine(cacheRoot,"launcher-error.txt"),e.ToString());}catch{}
            if(!test)MessageBox.Show("准备失败："+e.Message+"\n请检查磁盘空间与目录写入权限。","跳绳助手",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        } finally {if(form!=null)form.Dispose();}
    }
    class Slice:Stream {
        Stream source;long origin,length,position;
        public Slice(Stream source,long origin,long length){this.source=source;this.origin=origin;this.length=length;}
        public override bool CanRead{get{return true;}}public override bool CanSeek{get{return true;}}public override bool CanWrite{get{return false;}}
        public override long Length{get{return length;}}public override long Position{get{return position;}set{Seek(value,SeekOrigin.Begin);}}
        public override int Read(byte[] buffer,int offset,int count){source.Position=origin+position;int result=source.Read(buffer,offset,(int)Math.Min(count,length-position));position+=result;return result;}
        public override long Seek(long offset,SeekOrigin where){long next=where==SeekOrigin.Begin?offset:where==SeekOrigin.Current?position+offset:length+offset;if(next<0||next>length)throw new IOException();position=next;return next;}
        public override void Flush(){}public override void SetLength(long value){throw new NotSupportedException();}public override void Write(byte[] b,int o,int c){throw new NotSupportedException();}
    }
}

