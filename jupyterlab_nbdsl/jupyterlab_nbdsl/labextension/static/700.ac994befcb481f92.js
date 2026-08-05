"use strict";(self.rspackChunkjupyterlab_nbdsl=self.rspackChunkjupyterlab_nbdsl||[]).push([[700],{2646(e,t,n){var r=n(1601),o=n.n(r),a=n(6314),i=n.n(a)()(o());i.push([e.id,`/* A cell whose cached kernel state was invalidated by an upstream edit; it will
   re-run on the next execution. Marked, not hidden. */
.nbdsl-stale .jp-Cell-inputWrapper {
  border-left: 3px dashed var(--jp-warn-color1);
}

.nbdsl-stale .jp-Cell-outputWrapper {
  opacity: 0.5;
}

/* Rendered application/vnd.nbdsl.path+json: object badge, then the functor
   chain from source to target. All colours come from --jp-* so the widget
   tracks the active theme. */
.nbdsl-path {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 6px 4px;
  font-family: var(--jp-ui-font-family);
  font-size: var(--jp-ui-font-size1);
  color: var(--jp-ui-font-color1);
  overflow-x: auto;
}

.nbdsl-path-object {
  padding: 2px 8px;
  border-radius: 3px;
  font-family: var(--jp-code-font-family);
  font-weight: 600;
  color: var(--jp-ui-inverse-font-color1);
  background: var(--jp-brand-color1);
}

.nbdsl-path-chain {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nbdsl-path-node {
  padding: 2px 8px;
  border: 1px solid var(--jp-border-color2);
  border-radius: 3px;
  font-family: var(--jp-code-font-family);
  background: var(--jp-layout-color2);
}

/* Objects between successive functors are not named by the payload. */
.nbdsl-path-waypoint {
  padding: 0;
  width: 6px;
  height: 6px;
  border: none;
  border-radius: 50%;
  text-indent: -999px;
  overflow: hidden;
  background: var(--jp-border-color1);
}

/* A column: functor label on top, shaft-and-head below it. The bottom padding
   matches the label height so the shaft, not the column, centres on the
   node row. */
.nbdsl-path-arrow {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  padding-bottom: 14px;
  color: var(--jp-brand-color1);
}

.nbdsl-path-step {
  height: 14px;
  line-height: 14px;
  padding: 0 6px;
  text-align: center;
  font-family: var(--jp-code-font-family);
  font-size: var(--jp-ui-font-size0);
  color: var(--jp-ui-font-color2);
  white-space: nowrap;
}

/* ::before is the shaft; it grows to the label's width so the arrow spans
   the functor it is labelled with. */
.nbdsl-path-glyph {
  display: flex;
  align-items: center;
  font-size: 15px;
  line-height: 1;
}

.nbdsl-path-glyph::before {
  content: '';
  flex: 1 1 auto;
  min-width: 14px;
  height: 1.5px;
  margin-right: -3px;
  background: currentcolor;
}

.nbdsl-path-fallback {
  display: inline-block;
  margin: 0;
  padding: 6px 10px;
  border-radius: 3px;
  font-family: var(--jp-code-font-family);
  font-size: var(--jp-code-font-size);
  color: var(--jp-content-font-color1);
  background: var(--jp-layout-color2);
  white-space: pre-wrap;
}
`,""]),n.d(t,{},{A:i})},6314(e){e.exports=function(e){var t=[];return t.toString=function(){return this.map(function(t){var n="",r=void 0!==t[5];return t[4]&&(n+="@supports (".concat(t[4],") {")),t[2]&&(n+="@media ".concat(t[2]," {")),r&&(n+="@layer".concat(t[5].length>0?" ".concat(t[5]):""," {")),n+=e(t),r&&(n+="}"),t[2]&&(n+="}"),t[4]&&(n+="}"),n}).join("")},t.i=function(e,n,r,o,a){"string"==typeof e&&(e=[[null,e,void 0]]);var i={};if(r)for(var s=0;s<this.length;s++){var l=this[s][0];null!=l&&(i[l]=!0)}for(var c=0;c<e.length;c++){var p=[].concat(e[c]);r&&i[p[0]]||(void 0!==a&&(void 0===p[5]||(p[1]="@layer".concat(p[5].length>0?" ".concat(p[5]):""," {").concat(p[1],"}")),p[5]=a),n&&(p[2]&&(p[1]="@media ".concat(p[2]," {").concat(p[1],"}")),p[2]=n),o&&(p[4]?(p[1]="@supports (".concat(p[4],") {").concat(p[1],"}"),p[4]=o):p[4]="".concat(o)),t.push(p))}},t}},1601(e){e.exports=function(e){return e[1]}},5072(e){var t=[];function n(e){for(var n=-1,r=0;r<t.length;r++)if(t[r].identifier===e){n=r;break}return n}function r(e,r){for(var o={},a=[],i=0;i<e.length;i++){var s=e[i],l=r.base?s[0]+r.base:s[0],c=o[l]||0,p="".concat(l," ").concat(c);o[l]=c+1;var d=n(p),u={css:s[1],media:s[2],sourceMap:s[3],supports:s[4],layer:s[5]};if(-1!==d)t[d].references++,t[d].updater(u);else{var f=function(e,t){var n=t.domAPI(t);return n.update(e),function(t){t?(t.css!==e.css||t.media!==e.media||t.sourceMap!==e.sourceMap||t.supports!==e.supports||t.layer!==e.layer)&&n.update(e=t):n.remove()}}(u,r);r.byIndex=i,t.splice(i,0,{identifier:p,updater:f,references:1})}a.push(p)}return a}e.exports=function(e,o){var a=r(e=e||[],o=o||{});return function(e){e=e||[];for(var i=0;i<a.length;i++){var s=n(a[i]);t[s].references--}for(var l=r(e,o),c=0;c<a.length;c++){var p=n(a[c]);0===t[p].references&&(t[p].updater(),t.splice(p,1))}a=l}}},7659(e){var t={};e.exports=function(e,n){var r=function(e){if(void 0===t[e]){var n=document.querySelector(e);if(window.HTMLIFrameElement&&n instanceof window.HTMLIFrameElement)try{n=n.contentDocument.head}catch(e){n=null}t[e]=n}return t[e]}(e);if(!r)throw Error("Couldn't find a style target. This probably means that the value for the 'insert' parameter is invalid.");r.appendChild(n)}},540(e){e.exports=function(e){var t=document.createElement("style");return e.setAttributes(t,e.attributes),e.insert(t,e.options),t}},5056(e,t,n){e.exports=function(e){var t=n.nc;t&&e.setAttribute("nonce",t)}},7825(e){e.exports=function(e){if("u"<typeof document)return{update:function(){},remove:function(){}};var t=e.insertStyleElement(e);return{update:function(n){var r,o,a;r="",n.supports&&(r+="@supports (".concat(n.supports,") {")),n.media&&(r+="@media ".concat(n.media," {")),(o=void 0!==n.layer)&&(r+="@layer".concat(n.layer.length>0?" ".concat(n.layer):""," {")),r+=n.css,o&&(r+="}"),n.media&&(r+="}"),n.supports&&(r+="}"),(a=n.sourceMap)&&"u">typeof btoa&&(r+="\n/*# sourceMappingURL=data:application/json;base64,".concat(btoa(unescape(encodeURIComponent(JSON.stringify(a))))," */")),e.styleTagTransform(r,t,e.options)},remove:function(){var e;null===(e=t).parentNode||e.parentNode.removeChild(e)}}}},1113(e){e.exports=function(e,t){if(t.styleSheet)t.styleSheet.cssText=e;else{for(;t.firstChild;)t.removeChild(t.firstChild);t.appendChild(document.createTextNode(e))}}},5959(e,t,n){var r=n(5072),o=n.n(r),a=n(7825),i=n.n(a),s=n(7659),l=n.n(s),c=n(5056),p=n.n(c),d=n(540),u=n.n(d),f=n(1113),h=n.n(f),v=n(2646),b={};b.styleTagTransform=h(),b.setAttributes=p(),b.insert=l().bind(null,"head"),b.domAPI=i(),b.insertStyleElement=u(),o()(v.A,b),v.A&&v.A.locals&&v.A.locals}}]);