"""
测试从系统播放器获取专辑封面图片
Thumbnail 属性类型: IRandomAccessStreamReference
需要调用 OpenReadAsync() 获取流，再读取图片字节
"""

import subprocess
import base64
import os

POWERSHELL_THUMBNAIL_SCRIPT = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null

$sessionManager = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])

$currentSession = $sessionManager.GetCurrentSession()

if ($null -eq $currentSession) {
    Write-Output "ERROR: no_session"
    exit 0
}

$mediaProperties = Await ($currentSession.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])

# 输出基本信息
Write-Output ("TITLE: " + $mediaProperties.Title)
Write-Output ("ARTIST: " + $mediaProperties.Artist)

# 获取封面
$thumbnail = $mediaProperties.Thumbnail

if ($null -eq $thumbnail) {
    Write-Output "THUMBNAIL: null"
    exit 0
}

Write-Output "THUMBNAIL: found"

try {
    $stream = Await ($thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
    
    if ($null -eq $stream) {
        Write-Output "STREAM: null"
        exit 0
    }
    
    # 通过反射调用 AsStreamForRead 扩展方法
    # 先加载需要的程序集
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    
    # 查找 AsStreamForRead 方法
    $asStreamMethod = [System.IO.WindowsRuntimeStreamExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsStreamForRead' -and $_.GetParameters().Count -eq 1
    } | Select-Object -First 1
    
    if ($null -ne $asStreamMethod) {
        Write-Output "METHOD_FOUND: AsStreamForRead"
        $netStream = $asStreamMethod.Invoke($null, @($stream))
        
        $memStream = New-Object System.IO.MemoryStream
        $netStream.CopyTo($memStream)
        $bytes = $memStream.ToArray()
        
        Write-Output ("BYTES_LENGTH: " + $bytes.Length)
        
        if ($bytes.Length -gt 0) {
            $base64 = [Convert]::ToBase64String($bytes)
            Write-Output ("BASE64_LENGTH: " + $base64.Length)
            Write-Output "BASE64_START"
            Write-Output $base64
            Write-Output "BASE64_END"
        } else {
            Write-Output "ERROR: stream read 0 bytes"
        }
        
        $memStream.Dispose()
        $netStream.Dispose()
    } else {
        Write-Output "METHOD_NOT_FOUND: trying alternative"
        
        # 备选方案: 直接用 Buffer + DataReader
        $size = $stream.Size
        Write-Output ("RAW_SIZE: " + $size)
        
        $inputStream = $stream.GetInputStreamAt(0)
        $dataReader = [Windows.Storage.Streams.DataReader]::new($inputStream)
        $loadOp = $dataReader.LoadAsync($size)
        
        # 等待 LoadAsync (返回 uint32)
        $asTaskUint32 = $asTaskGeneric.MakeGenericMethod([uint32])
        $netTask = $asTaskUint32.Invoke($null, @($loadOp))
        $netTask.Wait(-1) | Out-Null
        $loaded = $netTask.Result
        
        Write-Output ("LOADED: " + $loaded)
        
        $bytes = New-Object byte[] $loaded
        $dataReader.ReadBytes($bytes)
        
        if ($bytes.Length -gt 0) {
            $base64 = [Convert]::ToBase64String($bytes)
            Write-Output "BASE64_START"
            Write-Output $base64
            Write-Output "BASE64_END"
        }
        
        $dataReader.Dispose()
    }
    
    $stream.Dispose()
    
} catch {
    Write-Output ("ERROR_MSG: " + $_.Exception.Message)
    Write-Output ("ERROR_TYPE: " + $_.Exception.GetType().FullName)
    Write-Output ("INNER: " + $_.Exception.InnerException)
    Write-Output ("STACK: " + $_.ScriptStackTrace)
}
"""

def test_thumbnail():
    print("=" * 60)
    print("测试获取系统播放器封面图片")
    print("=" * 60)
    
    result = subprocess.run(
        ['powershell', '-NoProfile', '-Command', POWERSHELL_THUMBNAIL_SCRIPT],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=15
    )
    
    print(f"\n返回码: {result.returncode}")
    
    if result.stderr:
        print(f"错误输出: {result.stderr[:500]}")
    
    lines = result.stdout.strip().split('\n')
    
    base64_data = None
    in_base64 = False
    base64_lines = []
    
    for line in lines:
        line = line.strip()
        
        if line == "BASE64_START":
            in_base64 = True
            continue
        elif line == "BASE64_END":
            in_base64 = False
            base64_data = ''.join(base64_lines)
            continue
        
        if in_base64:
            base64_lines.append(line)
        else:
            print(f"  {line}")
    
    if base64_data:
        print(f"\n  Base64 数据长度: {len(base64_data)}")
        
        # 解码并保存为图片
        try:
            img_bytes = base64.b64decode(base64_data)
            output_path = os.path.join(os.path.dirname(__file__), 'test_cover.png')
            with open(output_path, 'wb') as f:
                f.write(img_bytes)
            print(f"  图片已保存: {output_path}")
            print(f"  图片大小: {len(img_bytes)} 字节")
            print(f"\n  >>> 成功提取封面! <<<")
        except Exception as e:
            print(f"  保存图片失败: {e}")
    else:
        print(f"\n  未获取到封面数据")

if __name__ == "__main__":
    test_thumbnail()
