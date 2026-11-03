using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Chao2Harvester;

// Reserve the folder before starting Python so connection/import failures and
// stderr belong to the same run as its screenshots, actions and final report.
public sealed class RunHistory
{
    public const int Limit=5;
    private static readonly Regex RunName=new(@"^(?:\d{8}-\d{6}(?:-\d{3})?|\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}(?:_\d{3})?)$");
    public string Folder { get; }
    public string Token { get; }
    public List<string> CleanupErrors { get; }=[];
    private string ReportPath=>Path.Combine(Folder,"report.json");

    private RunHistory(string folder,string token) { Folder=folder;Token=token; }

    private static (DateTime When,int Suffix)? Order(string name)
    {
        if(!RunName.IsMatch(name))return null;
        bool legacy=name.Contains('-');int size=legacy?15:19;
        if(!DateTime.TryParseExact(name[..size],legacy?"yyyyMMdd-HHmmss":"yyyy_MM_dd_HH_mm_ss",
            CultureInfo.InvariantCulture,DateTimeStyles.None,out var date))return null;
        return (date,name.Length>size?int.Parse(name[(size+1)..],CultureInfo.InvariantCulture):0);
    }

    private static bool SafeFolder(string root,string path)=>
        Directory.Exists(path) && !File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint) &&
        string.Equals(Path.GetDirectoryName(Path.GetFullPath(path)),root,StringComparison.OrdinalIgnoreCase) &&
        Order(Path.GetFileName(path)) is not null && File.Exists(Path.Combine(path,"report.json"));

    public static RunHistory Start(string root,string mode,DateTimeOffset? clock=null)
    {
        root=Path.TrimEndingDirectorySeparator(Path.GetFullPath(root));Directory.CreateDirectory(root);
        var now=clock??DateTimeOffset.Now;
        string stamp=now.ToString("yyyy_MM_dd_HH_mm_ss",CultureInfo.InvariantCulture);
        var date=DateTime.ParseExact(stamp,"yyyy_MM_dd_HH_mm_ss",CultureInfo.InvariantCulture);
        int first=Directory.EnumerateDirectories(root).Select(p=>Order(Path.GetFileName(p)))
            .Where(v=>v.HasValue && v.Value.When==date).Select(v=>v!.Value.Suffix).DefaultIfEmpty(-1).Max()+1;
        for(int suffix=first;suffix<1000;suffix++)
        {
            string folder=Path.Combine(root,stamp+(suffix==0?"":$"_{suffix:000}"));
            if(Directory.Exists(folder)||File.Exists(folder))continue;
            Directory.CreateDirectory(folder);
            string token=Guid.NewGuid().ToString("N");
            var marker=new JsonObject { ["started"]=now.ToString("O"),["folder"]=folder,
                ["status"]="starting",["session_token"]=token,["mode"]=mode,
                ["tasks"]=new JsonObject(),["events"]=new JsonArray() };
            try
            {
                using var file=new FileStream(Path.Combine(folder,"report.json"),FileMode.CreateNew,FileAccess.Write,FileShare.Read);
                using var writer=new StreamWriter(file,new UTF8Encoding(false));
                writer.Write(marker.ToJsonString(new(){WriteIndented=true}));
            }
            catch(IOException) when(File.Exists(Path.Combine(folder,"report.json"))) { continue; }
            var run=new RunHistory(folder,token);run.Prune(root);return run;
        }
        throw new IOException("无法创建唯一的运行记录目录");
    }

    private void Prune(string root)
    {
        var old=Directory.EnumerateDirectories(root).Where(p=>SafeFolder(root,p))
            .OrderByDescending(p=>Order(Path.GetFileName(p))!.Value.When)
            .ThenByDescending(p=>Order(Path.GetFileName(p))!.Value.Suffix).Skip(Limit).ToArray();
        foreach(var folder in old)
            try
            {
                // Revalidate the absolute path immediately before recursive removal.
                if(!SafeFolder(root,folder))throw new IOException("目录已变化，未清理");
                Directory.Delete(folder,true);
            }
            catch(Exception error) when(error is IOException or UnauthorizedAccessException)
            { CleanupErrors.Add(Path.GetFileName(folder)+"："+error.Message); }
    }

    private JsonObject Read()=>JsonNode.Parse(File.ReadAllText(ReportPath))!.AsObject();
    private void Write(JsonObject value)
    {
        File.WriteAllText(ReportPath+".tmp",value.ToJsonString(new(){WriteIndented=true}),new UTF8Encoding(false));
        File.Move(ReportPath+".tmp",ReportPath,true);
    }
    public void Log(string time,string message,string color)=>File.AppendAllText(
        Path.Combine(Folder,"frontend-log.jsonl"),
        JsonSerializer.Serialize(new { time,message,color })+Environment.NewLine,new UTF8Encoding(false));
    public void SaveResult(JsonElement data)
    {
        var report=Read();
        foreach(var item in data.EnumerateObject())
            if(item.Name!="folder")report[item.Name]=JsonNode.Parse(item.Value.GetRawText());
        report["folder"]=Folder;report["finished"]??=DateTimeOffset.Now.ToString("O");Write(report);
    }
    public void Finish(string fallbackStatus,string reason)
    {
        var report=Read();
        if(report["status"]?.ToString() is "starting" or "running")
        { report["status"]=fallbackStatus;report["reason"]=reason; }
        report["finished"]??=DateTimeOffset.Now.ToString("O");Write(report);
    }
}
