param(
    [Parameter(Mandatory)] [string]$JobsFile
)
# Synthetisiert Turns über die WinRT-SpeechSynthesis-API (OneCore-Stimmen).
# JobsFile: UTF-8-JSON [{voice, text, out}, ...]

Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType=WindowsRuntime] | Out-Null

$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($op))
    $task.Wait() | Out-Null
    $task.Result
}

$jobs = Get-Content -Raw -Encoding UTF8 $JobsFile | ConvertFrom-Json
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices

foreach ($j in $jobs) {
    $voice = $all | Where-Object { $_.DisplayName -eq $j.voice }
    if (-not $voice) { throw "Stimme nicht gefunden: $($j.voice)" }
    $synth.Voice = $voice
    $stream = Await ($synth.SynthesizeTextToStreamAsync($j.text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $size = $stream.Size
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    Await ($reader.LoadAsync($size)) ([UInt32]) | Out-Null
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [System.IO.File]::WriteAllBytes($j.out, $bytes)
    Write-Output "OK $($j.voice) -> $($j.out)"
}
$synth.Dispose()
