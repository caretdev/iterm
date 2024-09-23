Class iTerm.Router Extends %CSP.REST
{

Parameter UseSession = 1;

Parameter Debug = 1;

ClassMethod OnPreDispatch(pUrl As %String, pMethod As %String, ByRef pContinue As %Boolean) As %Status [ Internal ]
{
  if $extract(pUrl, 1, 4) = "/pty" {
    do ##class(%Library.Device).ReDirectIO(0)
    quit ##class(iTerm.Engine).Page(0)
  }
  #if $piece($system.Version.GetNumber(),".",1,2)]]"2024.1"
  set debug = $$$GetSecurityApplicationsWSGIDebug(%request.AppData)
  if debug '= ..#Debug {
    do ..SetDebug(%request.Application, ..#Debug)
  }
  do %response.SetHeader("x-wsgidebug", debug)
  #endIf

	set staticFileDirectory = $$$GetSecurityApplicationsPath(%request.AppData)
  set serveStaticEnabled = 1
	set pContinue = 0
  if '$match(pUrl, "^/api(/.*)*$") {
    if pUrl = "/" set pUrl = "/index.html"
    quit ..StaticFiles(pUrl)
  }
  quit $$$OK

  if $piece(pUrl, "/", 3) '= "" {
    try {
      set namespace = $piece(pUrl, "/", 3)
      set $namespace = namespace
    }
    catch {
      set %response.Status = 403
      return $$$OK
    }
  }
  set params = 0

  #if $system.Version.GetNumber()]]"2024.1"
  set params = 1
  set params(1) = 1
  #endIf

	do ##class(%SYS.Python.WSGI).DispatchREST(pUrl, "", "terminal.app", "app", params...)
	quit $$$OK
}

ClassMethod AccessCheck(Output pAuthorized As %Boolean = 0) As %Status
{
  $$$QuitOnError(##super(.pAuthorized))
  if pAuthorized, $username'="UnknownUser" {
    if %request.Method="POST" {
      set %response.Redirect = %request.URL
    }
    quit $$$OK
  }
  quit $$$OK
}

ClassMethod Login(skipheader As %Boolean = 1) As %Status
{
  set tUrl = %request.URL
  set tUrl = "/"_$extract(tUrl,$length(%request.Application)+1,*)
  if $piece(tUrl, "/", 2) = "portal" {
    set %response.ServerSideRedirect = "/csp/sys" _ tUrl
    quit $$$OK
  }
  kill %request.Data("Error:ErrorCode")
  quit ##class(%CSP.Login).Page(skipheader)
}

ClassMethod SetDebug(app As %String = "/iterm", debug = 0)
{
  new $namespace
  set $namespace = "%SYS"
  set p("WSGIDebug") = 1
  quit ##class(Security.Applications).Modify(app, .p)
}

ClassMethod StaticFiles(pUrl) As %Status
{
  set name = $translate($piece(pUrl, "/", 2, *), "/.", "__")
  if ##class(%Dictionary.XDataDefinition).IDKEYExists($classname(), name, .id) {
    set obj = ##class(%Dictionary.XDataDefinition).%OpenId(id)
    set %response.ContentType = obj.MimeType
    quit obj.Data.OutputToDevice()
  }
  elseif ##class(%Dictionary.MethodDefinition).IDKEYExists($classname(), name, .id) {
    set obj = ##class(%Dictionary.MethodDefinition).%OpenId(id)
    set %response.ContentType = "application/javascript"
    quit obj.Implementation.OutputToDevice()
  }
  quit $$$OK
}

XData "index_html" [ MimeType = text/html ]
{
<!DOCTYPE html>
<html>
  <head>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm/css/xterm.css" />
    <link rel="stylesheet" href="terminal.css" />
  </head>
  <body>
    <div id="terminal"></div>
    <script src="https://cdn.jsdelivr.net/npm/@xterm/xterm"></script>
    <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit"></script>
    <script src="https://unpkg.com/socket.io@4.7.5/client-dist/socket.io.js"></script>
    <script src="terminal.js"></script>
  </body>
</html>
}

XData "terminal_css" [ MimeType = text/css ]
{
  html, body, #terminal, .terminal {
    width: 100vw;
    height: 100vh;
    padding: 0;
    margin: 0;
  }

  .terminal {
    padding: 0 1em;
  }
}

ClientMethod "terminal_js"() [ Language = javascript ]
{
  var term = new Terminal({
    convertEol: true,
    fontFamily: "Menlo, Monaco, Courier New, monospace",
    bellStyle: "sound",
    fontSize: 15,
    fontWeight: 400,
    cursorBlink: true,
  });
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById("terminal"));
  fitAddon.fit();
  document.body.onresize = function(){ fitAddon.fit(); };
  const params = new URL(document.location.toString()).searchParams;
  const ns = params.get("ns");
  var socket = io.connect({
    transports: ["websocket"],
    path: document.location.pathname + "pty" + ( ns ? "/" + encodeURIComponent(ns) : ""),
  });
  socket.on("connect", () => {
  });
  term.onData((key) => {
    socket.emit("pty-input", { input: key });
  });

  socket.on("pty-output", function (output) {
    term.write(output["output"]);
  });
}

ClientMethod "addonfit_js"() [ Language = javascript ]
{
  /**
  * Copyright (c) 2017 The xterm.js authors. All rights reserved.
  * @license MIT
  */

  import type { Terminal, ITerminalAddon } from '@xterm/xterm';
  import type { FitAddon as IFitApi } from '@xterm/addon-fit';
  import { IRenderDimensions } from 'browser/renderer/shared/Types';
  import { ViewportConstants } from 'browser/shared/Constants';

  interface ITerminalDimensions {
    /**
    * The number of rows in the terminal.
    */
    rows: number;

    /**
    * The number of columns in the terminal.
    */
    cols: number;
  }

  const MINIMUM_COLS = 2;
  const MINIMUM_ROWS = 1;

  export class FitAddon implements ITerminalAddon , IFitApi {
    private _terminal: Terminal | undefined;

    public activate(terminal: Terminal): void {
      this._terminal = terminal;
    }

    public dispose(): void {}

    public fit(): void {
      const dims = this.proposeDimensions();
      if (!dims || !this._terminal || isNaN(dims.cols) || isNaN(dims.rows)) {
        return;
      }

      // TODO: Remove reliance on private API
      const core = (this._terminal as any)._core;

      // Force a full render
      if (this._terminal.rows !== dims.rows || this._terminal.cols !== dims.cols) {
        core._renderService.clear();
        this._terminal.resize(dims.cols, dims.rows);
      }
    }

    public proposeDimensions(): ITerminalDimensions | undefined {
      if (!this._terminal) {
        return undefined;
      }

      if (!this._terminal.element || !this._terminal.element.parentElement) {
        return undefined;
      }

      // TODO: Remove reliance on private API
      const core = (this._terminal as any)._core;
      const dims: IRenderDimensions = core._renderService.dimensions;

      if (dims.css.cell.width === 0 || dims.css.cell.height === 0) {
        return undefined;
      }

      const scrollbarWidth = (this._terminal.options.scrollback === 0
        ? 0
        : (this._terminal.options.overviewRuler?.width || ViewportConstants.DEFAULT_SCROLL_BAR_WIDTH));

      const parentElementStyle = window.getComputedStyle(this._terminal.element.parentElement);
      const parentElementHeight = parseInt(parentElementStyle.getPropertyValue('height'));
      const parentElementWidth = Math.max(0, parseInt(parentElementStyle.getPropertyValue('width')));
      const elementStyle = window.getComputedStyle(this._terminal.element);
      const elementPadding = {
        top: parseInt(elementStyle.getPropertyValue('padding-top')),
        bottom: parseInt(elementStyle.getPropertyValue('padding-bottom')),
        right: parseInt(elementStyle.getPropertyValue('padding-right')),
        left: parseInt(elementStyle.getPropertyValue('padding-left'))
      };
      const elementPaddingVer = elementPadding.top + elementPadding.bottom;
      const elementPaddingHor = elementPadding.right + elementPadding.left;
      const availableHeight = parentElementHeight - elementPaddingVer;
      const availableWidth = parentElementWidth - elementPaddingHor - scrollbarWidth;
      const geometry = {
        cols: Math.max(MINIMUM_COLS, Math.floor(availableWidth / dims.css.cell.width)),
        rows: Math.max(MINIMUM_ROWS, Math.floor(availableHeight / dims.css.cell.height))
      };
      return geometry;
    }
  }
}

}
