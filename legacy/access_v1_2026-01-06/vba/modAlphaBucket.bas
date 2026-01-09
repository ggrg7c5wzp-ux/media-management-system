Attribute VB_Name = "modAlphaBucket"
Option Compare Database
Option Explicit

Public Function GetAlphaBucket_Old(ArtistName As String) As String

    Dim s As String
    Dim firstLetter As String
    
    s = Trim(ArtistName)
    
    ' If empty, return blank
    If s = "" Then
        GetAlphaBucket_Old = ""
        Exit Function
    End If
    
    ' Normalize to lower for prefix checks
    s = LCase$(s)
    
    ' Strip leading articles
    If Left$(s, 2) = "a " Then
        s = Mid$(s, 3)
    ElseIf Left$(s, 3) = "an " Then
        s = Mid$(s, 4)
    ElseIf Left$(s, 4) = "the " Then
        s = Mid$(s, 5)
    End If
    
    s = Trim(s)
    If s = "" Then
        GetAlphaBucket_Old = ""
        Exit Function
    End If
    
    ' Strip leading non-letters (handles things like 'Til Tuesday)
    Do While Len(s) > 0 And Not (Mid$(s, 1, 1) Like "[A-Za-z]")
        s = Mid$(s, 2)
    Loop
    
    If s = "" Then
        GetAlphaBucket_Old = ""
        Exit Function
    End If
    
    ' Use first letter, uppercase
    firstLetter = UCase$(Left$(s, 1))
    GetAlphaBucket_Old = firstLetter
End Function

