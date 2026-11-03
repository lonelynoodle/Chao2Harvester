using System.IO;
using System.Text;
using System.Text.Json.Nodes;

namespace Chao2Harvester;

public partial class MainWindow
{
    public TaskItem TriggerEventsTool { get; }=new("trigger_events","触发事件","",true);
    private bool triggerSettingsReady;
    private string? triggerSmokePath;
    private string triggerSaveError="";
    public string TriggerSaveError { get=>triggerSaveError; private set { triggerSaveError=value;Changed(); } }
    public bool MerchantEventEnabled=>TriggerEventsTool.Options.FirstOrDefault(o=>o.Key=="merchant")?.Checked ?? true;

    private void InitializeTriggerEvents(JsonArray toolSpecs)
    {
        var spec=toolSpecs.First(t=>t!["key"]!.GetValue<string>()=="trigger_events")!;
        foreach(var field in spec["fields"]!.AsArray())
        {
            var option=new TaskOption(field!,settings["trigger_events"]?[field!["key"]!.GetValue<string>()]);
            option.PropertyChanged+=(_,e)=>{
                if(e.PropertyName!=nameof(TaskOption.Checked))return;
                Changed(nameof(MerchantEventEnabled));AutoSaveTriggerEvents();
            };
            TriggerEventsTool.Options.Add(option);
        }
    }

    private void AutoSaveTriggerEvents()
    {
        if(!triggerSettingsReady)return;
        try
        {
            var snapshot=TriggerEventsTool.SaveOptions();
            if(!App.Smoke || triggerSmokePath is not null)
            {
                string path=triggerSmokePath ?? Path.Combine(App.Root,"config.json");
                var saved=JsonNode.Parse(File.ReadAllText(path))!.AsObject();
                saved["trigger_events"]=snapshot.DeepClone();
                File.WriteAllText(path+".events.tmp",saved.ToJsonString(new() { WriteIndented=true }),new UTF8Encoding(false));
                File.Move(path+".events.tmp",path,true);
            }
            settings["trigger_events"]=snapshot;TriggerSaveError="";
        }
        catch(Exception e) { TriggerSaveError="自动保存失败："+e.Message; }
    }
}
